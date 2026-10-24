"""影片連結 → 逐字稿 → explain-ladder 四層（1 寫作、2 圖解＋資訊圖、3 網頁、4 口白稿）
每一步的輸出已經存在就跳過，所以失敗後重跑只會補沒做完的。"""
import html, json, os, pathlib, re, shutil, subprocess, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent
JOBS = ROOT / "jobs"
# 本機設定（不進 git）：local.json 可以放 python／whisper／skill 的路徑、讀者預設、.env 位置；環境變數優先於它
LOCAL = json.loads((ROOT / "local.json").read_text(encoding="utf-8")) if (ROOT / "local.json").exists() else {}


def _first(*cands):
    for c in cands:
        if c and pathlib.Path(c).exists():
            return pathlib.Path(c)
    return pathlib.Path(cands[-1])


SKILL = _first(os.environ.get("EXPLAIN_LADDER_SKILL"), LOCAL.get("skill"), ROOT / "skill/SKILL.md")
YTDLP = "yt-dlp"
WHISPER = str(_first(os.environ.get("EXPLAIN_LADDER_WHISPER"), LOCAL.get("whisper"), shutil.which("mlx_whisper"), os.path.expanduser("~/.local/bin/mlx_whisper")))
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
# 出圖要 PIL（Gemini 模式還要 google-genai）：用 EXPLAIN_LADDER_PYTHON 或 local.json 的 python 指到有裝 Pillow 的 python
GEMINI_PY = str(_first(os.environ.get("EXPLAIN_LADDER_PYTHON"), LOCAL.get("python"), __import__("sys").executable))
STEPS = ["逐字稿", "1 寫作", "2 圖解", "出圖", "3 網頁", "4 口白稿"]
HOSTS = ("youtube.com", "youtu.be", "bilibili.com", "b23.tv", "podcasts.apple.com")
DEFAULT_READER = os.environ.get("EXPLAIN_LADDER_READER") or LOCAL.get("reader") or "一般讀者（不熟這個主題、想快點懂的上班族）"
SOURCES = ("subs", "zh", "auto")   # 逐字稿來源：字幕優先｜聽寫中文原聲｜聽寫（自動判斷語言）
DRAWS = ("mermaid", "gemini")      # 出圖：Chrome 渲染 Mermaid（免費，預設）｜Gemini Pro 資訊圖（要花錢）


def valid_url(url):
    m = re.match(r"https?://([^/]+)/\S+$", url.strip())
    return bool(m) and any(m.group(1) == h or m.group(1).endswith("." + h) for h in HOSTS)


def apple_ids(url):
    """Apple Podcasts 連結 → (節目 ID, 單集 ID)；節目頁沒有單集 ID 回 (節目 ID, None)；不是 Apple Podcasts 回 None"""
    m = re.match(r"https?://podcasts\.apple\.com/\S*?/id(\d+)", url.strip())
    if not m:
        return None
    e = re.search(r"[?&]i=(\d+)", url)
    return m.group(1), e.group(1) if e else None


def url_error(url):
    """可以收就回空字串，不能收就回給使用者看的說明"""
    if not valid_url(url):
        return "只收 YouTube、bilibili 的影片連結，或 Apple Podcasts 的單集連結"
    ids = apple_ids(url)
    if ids and not ids[1]:
        return "這是整個節目的連結。請在 Apple Podcasts 的單集按「分享」→「拷貝連結」，改貼單集連結"
    return ""


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(f"{pathlib.Path(cmd[0]).name} 失敗：{(r.stderr or r.stdout).strip()[-600:]}")
    return r.stdout


def llm(system, prompt):
    """唯一呼叫模型的地方。現在走本機已登入的 claude CLI；要換成 Anthropic API 只改這個函數
    cwd 放在家目錄外面：~/CLAUDE.md 的工作規則（先問再做）不該套到這裡的單次產文"""
    out = sh(["claude", "-p", "--system-prompt", system, "--tools", "", "--no-session-persistence", "--disable-slash-commands"],
             input=prompt, cwd=tempfile.gettempdir(), timeout=1800).strip()
    m = re.match(r"```\w*\n(.*)\n```$", out, re.S)   # 模型偶爾把整份包進程式碼框
    return m.group(1) if m else out


# ── 逐字稿 ──────────────────────────────────────────────

def apple_pick(results, episode):
    """Apple 查詢 API 的結果裡，找出這一集的標題、節目名、長度（秒）、說明、音檔網址"""
    for r in results:
        if str(r.get("trackId")) == str(episode) and r.get("episodeUrl"):
            return {"title": r.get("trackName") or "", "uploader": r.get("collectionName") or r.get("artistName") or "",
                    "duration": (r.get("trackTimeMillis") or 0) // 1000, "description": r.get("description") or "", "audio": r["episodeUrl"]}
    raise RuntimeError("在 Apple Podcasts 找不到這一集（Apple 的查詢只列最新 200 集）")


def apple_episode(url):
    """節目頁 yt-dlp 不支援，所以用 Apple 的公開查詢 API 找音檔（不用解析 RSS：這台 Homebrew Python 的 XML 模組壞了，10-16）"""
    show, episode = apple_ids(url)
    out = sh(["curl", "-sL", "--fail", "-m", "60", f"https://itunes.apple.com/lookup?id={show}&entity=podcastEpisode&limit=200"])
    return apple_pick(json.loads(out)["results"], episode)


def whisper(job, audio, lang):
    """本機聽寫 → 純文字；lang 空字串就讓模型自己判斷語言"""
    cmd = [WHISPER, str(audio), "--model", WHISPER_MODEL, "--output-format", "vtt", "--output-dir", str(job),
           "--condition-on-previous-text", "False"]   # 長片開著這個容易卡在同一句一直重複
    if lang.startswith("zh"):
        cmd += ["--language", "zh", "--initial-prompt", "以下是繁體中文的逐字稿。"]
    elif lang:
        cmd += ["--language", lang[:2]]
    sh(cmd)
    text = vtt_to_text((job / f"{audio.stem}.vtt").read_text(encoding="utf-8"))
    audio.unlink()
    return text


def podcast_transcript(job, st):
    ep = apple_episode(st["url"])
    st.update(title=ep["title"], uploader=ep["uploader"], duration=ep["duration"], note="本機聽寫中（長的節目要等比較久）")
    save(job, st)
    (job / "影片說明.txt").write_text(ep["description"][:4000], encoding="utf-8")
    ext = re.search(r"\.(mp3|m4a|aac|wav)(?:\?|$)", ep["audio"])
    audio = job / f"audio.{ext.group(1) if ext else 'mp3'}"
    sh(["curl", "-sL", "--fail", "-m", "1800", "-o", str(audio), ep["audio"]])
    text = whisper(job, audio, "zh" if st.get("source") == "zh" else "")
    st["note"] = "逐字稿來源：Podcast 音檔，本機聽寫（mlx_whisper）；人名、專有名詞可能聽錯"
    (job / "逐字稿.txt").write_text(text, encoding="utf-8")


def pick_subs(info):
    """回傳 (語言代碼, 是不是自動字幕)；沒有可用的字幕回傳 None（改用聽寫）
    自動字幕只收原語言的：YouTube 機翻的那幾十種不收"""
    subs = [k for k in (info.get("subtitles") or {}) if k not in ("live_chat", "danmaku")]
    subs.sort(key=lambda k: not re.search("hant|tw|hk", k.lower()))   # 繁體排前面
    lang = info.get("language") or ""
    if lang:   # 知道原聲語言：別種語言的上傳字幕多半是翻譯，不收（10-12 曾鳴訪談：中文訪談只有 AI 翻的英文字幕）
        subs = [k for k in subs if k.lower()[:2] == lang.lower()[:2]]
    for pre in ("zh", "en"):
        for k in subs:
            if k.lower().startswith(pre):
                return k, False
    if subs:
        return subs[0], False
    for k in info.get("automatic_captions") or {}:
        if k.endswith("-orig") or k == lang:
            return k, True
    return None


CUE = re.compile(r"(?:(\d+):)?(\d\d):(\d\d)\.\d{3}\s+-->")

def vtt_to_text(vtt, every=300):
    """字幕檔 → 純文字；每 every 秒留一個 [時:分:秒]，寫作層可以標出處"""
    out, last, t, mark = [], "", 0, -every
    for line in vtt.splitlines():
        line = line.strip()
        m = CUE.match(line)
        if m:
            t = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            continue
        if not line or line.isdigit() or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")):
            continue
        line = re.sub(r"<[^>]+>", "", html.unescape(line)).strip()   # 先還原再去標籤：有的字幕把 <b> 寫成 &lt;b&gt;
        if not line or line == last:   # 自動字幕會把同一行重複好幾次
            continue
        if t - mark >= every:
            out.append(f"\n[{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}]")
            mark = t
        out.append(line)
        last = line
    return "\n".join(out).strip()


def transcript(job, st):
    url = st["url"]
    if apple_ids(url):
        return podcast_transcript(job, st)
    info = json.loads(sh([YTDLP, "-J", "--no-playlist", url]))
    st.update(title=info.get("title") or "", uploader=info.get("uploader") or info.get("channel") or "", duration=info.get("duration") or 0)
    save(job, st)
    source = st.get("source", "subs")
    text, pick = "", pick_subs(info) if source == "subs" else None
    (job / "影片說明.txt").write_text((info.get("description") or "")[:4000], encoding="utf-8")
    if pick:
        lang, auto = pick
        subprocess.run([YTDLP, "--skip-download", "--no-playlist", "--write-auto-subs" if auto else "--write-subs", "--sub-langs", lang,
                        "--sub-format", "vtt/best", "--convert-subs", "vtt", "-o", str(job / "sub"), url], capture_output=True)
        f = next(job.glob("sub*.vtt"), None)
        if f:
            text = vtt_to_text(f.read_text(encoding="utf-8"))
            st["note"] = f"逐字稿來源：{'自動' if auto else '上傳的'}字幕（{lang}）"
    if len(text) < 200:
        st["note"] = "本機聽寫中（長片要等比較久）"
        save(job, st)
        lang = "zh" if source == "zh" else info.get("language") or ("zh" if "bili" in url or "b23" in url else "")
        audio = [YTDLP, "--no-playlist", "-f", "bestaudio/best", "-x", "--audio-format", "m4a", "-o", str(job / "audio.%(ext)s"), url]
        for client in ("", "android", "mweb"):   # YouTube 預設的播放端有時回 403（10-12）；換手機端就抓得到
            try:
                sh(audio + (["--extractor-args", f"youtube:player_client={client}"] if client else []))
                break
            except RuntimeError:
                if client == "mweb":
                    raise
        text = whisper(job, job / "audio.m4a", lang)
        st["note"] = "逐字稿來源：本機聽寫原聲（mlx_whisper）；人名、專有名詞可能聽錯"
    (job / "逐字稿.txt").write_text(text, encoding="utf-8")


# ── 四層 ────────────────────────────────────────────────

SYSTEM = """你把一支影片的內容，照下面這份 skill 的規則整理成好懂的教材。讀者是：{reader}
一律用繁體中文（台灣用語）。只根據逐字稿寫，不補逐字稿沒有的事實；人名、公司名、數字聽不清楚、可能聽錯或譯錯的，後面加（？）。影片說明裡有寫的人名和名詞，以影片說明為準。
只輸出檔案本身的內容，不要前言、不要結語、不要問問題。

===== skill：explain-ladder =====
"""

P1 = """寫第 1 層〈寫作〉，Markdown。

格式：
# 影片標題（繁體中文）
> 來源：頻道｜長度｜連結
## 一句話結論
## 用詞表（詞｜在本文的意思；只列這支影片的關鍵詞，之後每個詞照表用）
## 重點（依影片的論點分 5–9 節；每節先一句結論，再用短句說理由和例子；每節標題後面標出處時間，例如〔0:35:00〕）
## 對〈讀者的稱呼〉有用的地方（3 條以內：這支影片的哪個想法，讀者可以拿去用；對著讀者的身分和他關心的事寫；逐字稿沒有支持的不要硬寫）
## 講者沒有回答或互相矛盾的地方（沒有就寫「沒有」）

照 skill 第 1 層的規則：一字一義、句子短、主動句、先講結論。

影片資訊：
{meta}

影片說明（上傳者寫的，人名和名詞以這裡為準）：
{desc}

逐字稿（[時:分:秒] 是時間標記）：
{transcript}"""

P2 = """寫第 2 層〈圖解〉，Markdown。從下面這份第 1 層寫作裡，挑最值得畫的 3 到 4 件事，一張圖一件事。

每張圖的格式要完全照這樣（標題用「圖一」「圖二」…）：
## 圖一　這張圖的標題
```mermaid
flowchart TD
  A[短的節點文字] --> B{{是不是？}}
```
這張圖要說的一句話。

規則：
- 流程、結構用 Mermaid 的 flowchart（只用 flowchart；節點代號用英文字母，節點文字 12 個字以內）
- 好幾個選項一起比的，用 Markdown 表格，不用 Mermaid
- 圖下的說明最多兩行

第 1 層寫作：
{l1}"""

P3 = """寫第 3 層〈網頁〉：一個完整的 HTML 檔，輸出從 <!doctype html> 開始，<head> 裡要有 <meta charset="utf-8"> 和 viewport。

⭐ 版型已經定好：程式會自動把「星智未來版型」（色彩、字型、元件）插進 <head>。
- 不要自己寫 :root 的色彩、不要指定字型、不要寫 body 的背景；需要的顏色一律用 var(--ink)、var(--muted)、var(--up)、var(--down)、var(--mark) 這些變數。
- 版面用下面這些 class 組起來；真的需要新的 CSS，只能用上面的變數，而且要少。
{house}

⭐ 先判斷，再動手：先看第 1 層的內容是哪一種，再選形式。
- 講座、訪談、課程（一個人講一套道理）：重點可以點開看細節（details）；有數字關係或因果才做一個滑桿試算，沒有就不要硬做；最後可以有 4–6 題小測驗。
- 新聞、週報（很多則消息、可信度不一）：做成卡片牆，可以依類別、可信度篩選；不需要小測驗。
- 資料、統計（一堆數字）：先放最重要的幾個數字（.nums），再放可以拉的試算或篩選表。
- 比較（幾個選項）：用表格（.tbl）或並排的卡片。
形式要從內容長出來，不要每一份都長一樣。

一定要有：
- 開頭：.eyebrow（來源和日期）、h1（標題）、.lede（一句話結論）
- 上方用 nav 的錨點連結跳到各段（<a href="#段落id">）。⚠️ 不要做「點了才顯示」的隱藏分頁：頁面打開就要完整可讀，捲下去就看得到全部。
- 圖解：{images}
- 「對讀者有用的地方」那一段，用 .card.hl 標出來

設計守則：
- 至少放一個只有這個主題才有的細節，當成內容，不是裝飾（例如它自己的單位、慣用的說法、原文的標記）。
- 避開看起來像 AI 做的版型：emoji 當段落標記、每一塊都加陰影、紫藍漸層、全部置中、沒有順序意義卻編 01／02／03。
- 編號只用在真的有先後順序的東西上。
- 手機寬度（約 400px）也要能看，頁面不能左右捲動；寬的表格放在 .tbl 裡。
- 文字照 skill 第 1 層的規則：一句話先講結論、短句、一詞一義。
- 不用任何外部框架；JavaScript 寫在檔案最後，不用 alert／confirm。

第 1 層寫作：
{l1}

第 2 層圖解：
{l2}"""

P4 = """寫第 4 層〈影片〉的口白稿，Markdown。這一版只寫稿，不做影片。

格式：
# 口白稿：標題
> 長度目標：3 分鐘以內（約 650 字）
然後一張表：段落｜秒數｜畫面（用哪一張圖、或什麼字卡）｜口白（念出來的字，一字不差）

規則：開頭 5 秒先講結論；口白照 skill 第 1 層（短句、口語、念得順）；畫面盡量用第 2 層已經有的圖。

第 1 層寫作：
{l1}

第 2 層圖解：
{l2}"""


HOUSE_CSS = ROOT / "house.css"
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@600;900'
         '&family=Noto+Sans+TC:wght@400;500;700&family=IBM+Plex+Mono:wght@500;600&display=swap">')


def apply_house_style(html):
    """把星智未來版型插在 </head> 前面（charset 要留在檔案最前面）；已經插過就不再插"""
    if "星智未來版型" in html:
        return html
    block = FONTS + "\n<style>\n" + HOUSE_CSS.read_text(encoding="utf-8") + "\n</style>\n"
    i = html.lower().find("</head>")
    return html[:i] + block + html[i:] if i >= 0 else block + html


def page_prompt(images, l1, l2):
    css = HOUSE_CSS.read_text(encoding="utf-8")
    guide = css[css.index("可用的 class："):css.index("*/")].strip()
    return P3.format(house=guide, images=images, l1=l1, l2=l2)


def attach_profile(job, profile, filename):
    """讀者檔（.md）存進工作資料夾；jobs/ 不進 git"""
    (job / "讀者.md").write_text(profile, encoding="utf-8")
    st = load(job)
    st["profile"] = filename
    save(job, st)


def reader_text(job, st):
    """讀者的一句話描述；有讀者檔就整份附上"""
    reader = st.get("reader") or DEFAULT_READER
    f = job / "讀者.md"
    if not f.exists():
        return reader
    return (reader + "\n\n下面是讀者檔。寫「對讀者有用的地方」、挑重點、決定用詞時，照這份判斷讀者在意什麼、怎麼溝通；"
            "讀者檔裡的事實不是逐字稿的內容，不能寫成影片或文件說的。\n<讀者檔>\n" + f.read_text(encoding="utf-8") + "\n</讀者檔>")


def meta_text(st):
    """告訴模型這份內容是什麼。上傳的 .md 沒有頻道、長度、連結、時間標記，要明講，不然模型會寫「未提供」"""
    if st.get("source") == "md":
        f = st.get("file", "")
        return (f"標題：{st['title']}\n這份不是影片，是上傳的文字檔（{f}）：沒有頻道、長度、連結，也沒有時間標記。\n"
                f"「> 來源：」那一行寫成「> 來源：上傳的文字檔（{f}）」；重點的出處改標原文的章節標題，不標時間。")
    mins = int(st.get("duration") or 0) // 60
    return f"標題：{st['title']}\n頻道：{st.get('uploader', '')}\n長度：{mins} 分鐘\n連結：{st['url']}\n{st.get('note', '')}"


def layers(job, st, step):
    system = SYSTEM.replace("{reader}", reader_text(job, st)) + SKILL.read_text(encoding="utf-8")
    read = lambda name: (job / name).read_text(encoding="utf-8")
    write = lambda name, text: (job / name).write_text(text, encoding="utf-8")
    meta = meta_text(st)

    step("1 寫作", "1_寫作.md", lambda: write("1_寫作.md", llm(system, P1.format(meta=meta, desc=read("影片說明.txt"), transcript=read("逐字稿.txt")))))
    step("2 圖解", "2_圖解.md", lambda: write("2_圖解.md", llm(system, P2.format(l1=read("1_寫作.md")))))

    def draw():
        r = subprocess.run([GEMINI_PY, str(ROOT / "diagrams.py"), str(job)] + (["--gemini"] if st.get("draw") == "gemini" else []),
                           capture_output=True, text=True)
        (job / "出圖.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        if r.returncode or "❌" in r.stdout:
            st["note"] += "｜有圖沒出成功，看 出圖.log；按「重跑」會補"
    step("出圖", None, draw)

    def page():
        pngs = sorted(p.name for p in (job / "圖").glob("圖*.png")) if (job / "圖").exists() else []
        images = ("第 2 層的圖已經出成資訊圖，放在同一個資料夾的 " + "、".join(f"圖/{p}" for p in pngs) + "。用 <img> 依序放進來，每張下面寫圖的那一句話"
                  if pngs else "把第 2 層的每張圖用 HTML 和 CSS 重畫（方塊和箭頭），每張下面寫圖的那一句話")
        write("3_網頁.html", apply_house_style(llm(system, page_prompt(images, read("1_寫作.md"), read("2_圖解.md")))))
    step("3 網頁", "3_網頁.html", page)

    step("4 口白稿", "4_影片_口白稿.md", lambda: write("4_影片_口白稿.md", llm(system, P4.format(l1=read("1_寫作.md"), l2=read("2_圖解.md")))))


# ── 工作 ────────────────────────────────────────────────

def save(job, st):
    (job / "status.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")

def load(job):
    return json.loads((job / "status.json").read_text(encoding="utf-8"))

def new_job(url, reader="", source="subs", draw="mermaid"):
    job = JOBS / time.strftime("%Y%m%d-%H%M%S")
    job.mkdir(parents=True)
    save(job, {"id": job.name, "url": url, "reader": reader.strip() or DEFAULT_READER, "source": source if source in SOURCES else "subs",
               "draw": draw if draw in DRAWS else "mermaid", "title": "", "note": "", "error": "", "running": True, "steps": {s: "等待" for s in STEPS}})
    return job


TRASH = pathlib.Path.home() / ".Trash"

def delete_job(job_id):
    """移到垃圾桶，不直接刪：刪錯了可以從 Finder 的垃圾桶撿回來"""
    if not re.fullmatch(r"\d{8}-\d{6}", job_id or ""):
        raise RuntimeError("工作代號不對")
    job = JOBS / job_id
    if not (job / "status.json").exists():
        raise RuntimeError("找不到這個工作")
    if load(job)["running"]:
        raise RuntimeError("還在跑，跑完才能刪")
    dst = TRASH / f"explain-ladder-{job_id}"
    if dst.exists():
        dst = TRASH / f"explain-ladder-{job_id}-{time.strftime('%H%M%S')}"
    shutil.move(str(job), str(dst))


def pdf_to_text(data):
    """PDF → 純文字（poppler 的 pdftotext）；抽不出字就說，不要送空白給模型"""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data); f.flush()
        text = sh(["pdftotext", "-enc", "UTF-8", f.name, "-"])
    if len(re.sub(r"\s", "", text)) < 20:
        raise RuntimeError("這份 PDF 抽不出文字（可能是掃描的圖片），請改傳有文字的 PDF 或 .md")
    return text


MD_MAX = 2_000_000   # 字數上限；一份週報約幾萬字

def md_error(md):
    """可以收就回空字串，不能收就回給使用者看的說明"""
    if not md.strip():
        return "檔案是空的"
    if len(md) > MD_MAX:
        return f"檔案太大（超過 {MD_MAX:,} 字）"
    return ""


def new_md_job(md, filename, reader="", draw="mermaid"):
    """上傳的 .md 直接當逐字稿：run() 看到 逐字稿.txt 已經存在，就會跳過下載和聽寫"""
    job = new_job("", reader, "subs", draw)
    st = load(job)
    head = re.search(r"^#\s+(.+)$", md, re.M)
    st.update(source="md", file=filename, title=head.group(1).strip() if head else pathlib.Path(filename).stem,
              note=f"逐字稿來源：上傳的檔案（{filename}）")
    (job / "逐字稿.txt").write_text(md, encoding="utf-8")
    (job / "影片說明.txt").write_text("", encoding="utf-8")
    save(job, st)
    return job


def run(job):
    st = load(job)
    st.update(error="", running=True)

    def step(name, out, fn):
        if out and (job / out).exists():
            st["steps"][name] = "完成"
        else:
            st["steps"][name] = "進行中"
            save(job, st)
            fn()
            st["steps"][name] = "完成"
        save(job, st)

    try:
        step("逐字稿", "逐字稿.txt", lambda: transcript(job, st))
        layers(job, st, step)
    except Exception as e:
        for name, state in st["steps"].items():
            if state == "進行中":
                st["steps"][name] = "失敗"
        st["error"] = str(e)
    st["running"] = False
    save(job, st)
