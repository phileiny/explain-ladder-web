"""第 4 層影片的共用工具：口白 → 句子和字幕的時間表、用 Chrome 把動畫網頁一格一格輸出。
動畫照 awesome-opus5-5-videos 的做法：畫面是程式寫的網頁，網頁提供 window.seek(秒)，每一格都由時間算出來，不靠即時播放。
用法見各工作資料夾的 4_影片/build.py。要用有裝 websockets 的 python 跑。"""
import base64, json, pathlib, re, subprocess, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def sentences(text):
    """照 。？！ 切句（動畫的出場時間對著句子）"""
    return [s for s in re.findall(r"[^。？！]+[。？！]?", text.strip()) if s.strip()]


def sub_lines(sentence, limit=26):
    """一句太長就在最靠近中間的逗號切開，直到每行不超過 limit 個字（字幕一行放得下）"""
    s = sentence.strip().rstrip("。")
    if len(s) <= limit:
        return [s]
    cuts = [i for i, c in enumerate(s) if c in "，：、；" and 3 < i < len(s) - 4]
    if not cuts:
        return [s]
    i = min(cuts, key=lambda k: abs(k - len(s) / 2))
    return sub_lines(s[:i + 1].rstrip("，、；"), limit) + sub_lines(s[i + 1:], limit)


def timing(segs, durations=None, fps=30, gap=0.35, per_char=0.235):
    """segs: [(id, 口白)]；durations: {id: 實際口白秒數}（沒有就用字數估）。回傳給動畫和合成用的時間表
    每一段＝口白長度＋gap 的停頓；句子和字幕在段內照字數分配時間"""
    out, t = [], 0.0
    for sid, text in segs:
        sents = sentences(text)
        n = sum(len(s) for s in sents)
        voice = durations[sid] if durations else n * per_char
        dur = voice + gap
        sent, subs, st = [], [], 0.0
        for s in sents:
            d = voice * len(s) / n
            sent.append({"start": round(st, 3), "dur": round(d, 3), "text": s})
            lines = sub_lines(s); m = sum(len(x) for x in lines); lt = st
            for line in lines:
                ld = d * len(line) / m
                subs.append({"start": round(t + lt, 3), "end": round(t + lt + ld, 3), "text": line})
                lt += ld
            st += d
        out.append({"id": sid, "start": round(t, 3), "dur": round(dur, 3), "voice": round(voice, 3), "sent": sent, "subs": subs})
        t += dur
    return {"fps": fps, "total": round(t, 3), "estimated": durations is None, "segs": out}


class Page:
    """開一個無頭 Chrome，用 DevTools 協定控制同一個分頁（比每一格重開一次 Chrome 快上百倍）"""

    def __init__(self, html, width=1920, height=1080, port=9333):
        from websockets.sync.client import connect
        self.proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", "--remote-allow-origins=*",
                                      "--hide-scrollbars", "--disable-gpu", f"--window-size={width},{height}",
                                      "--force-device-scale-factor=1", "--allow-file-access-from-files", f"--user-data-dir=/tmp/elw-chrome-{port}", pathlib.Path(html).as_uri()],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        else:
            self.proc.kill(); raise RuntimeError("Chrome 沒有起來")
        self.ws, self.n = connect(page["webSocketDebuggerUrl"], max_size=None), 0
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
        self.eval("new Promise(r => { const go = () => document.fonts.ready.then(r); document.readyState === 'complete' ? go() : addEventListener('load', go); })")

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                if "error" in m: raise RuntimeError(f"{method}: {m['error']}")
                return m["result"]

    def eval(self, js):
        r = self.call("Runtime.evaluate", expression=js, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", str(r["exceptionDetails"])))
        return r["result"].get("value")

    def shot(self, path, fmt="png", quality=None):
        p = {"format": fmt}
        if quality: p["quality"] = quality
        pathlib.Path(path).write_bytes(base64.b64decode(self.call("Page.captureScreenshot", **p)["data"]))

    def close(self):
        try: self.ws.close()
        finally: self.proc.terminate()


def render(html, timing_json, out_dir, times=None):
    """times 給一串秒數＝只出這幾格（檢查用，PNG）；不給＝照 fps 出整支（JPEG，檔名 f000001.jpg…）"""
    T = json.loads(pathlib.Path(timing_json).read_text(encoding="utf-8"))
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    page = Page(html)
    try:
        page.eval(f"init({json.dumps(T, ensure_ascii=False)})")
        page.eval("Promise.all([...document.fonts].map(f => f.load()))")   # 自帶的字型先載完，第一格才不會用到替代字
        if times is not None:
            for k, t in enumerate(times):
                page.eval(f"seek({t})"); page.shot(out / f"still_{k + 1:02d}.png")
            return len(times)
        n = int(T["total"] * T["fps"])
        for f in range(n):
            page.eval(f"seek({f / T['fps']})"); page.shot(out / f"f{f + 1:06d}.jpg", "jpeg", 93)
        return n
    finally:
        page.close()
