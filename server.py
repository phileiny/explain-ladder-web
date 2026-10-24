"""explain-ladder-web：貼影片連結，產出四層內容。只給本機用（綁 127.0.0.1）。
用法：python3 server.py  → http://127.0.0.1:8765"""
import base64, json, mimetypes, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import pipeline

PORT = 8765
INDEX = pipeline.ROOT / "static/index.html"


def jobs():
    out = []
    for f in sorted(pipeline.JOBS.glob("*/status.json"), reverse=True):
        st = json.loads(f.read_text(encoding="utf-8"))
        st["files"] = sorted(str(p.relative_to(f.parent)) for p in f.parent.rglob("*")
                             if p.is_file() and not p.name.startswith(("_", ".")) and p.name != "status.json")
        out.append(st)
    return out


def start(job):
    threading.Thread(target=pipeline.run, args=(job,), daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path == "/":
            return self.send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/jobs":
            return self.send(200, jobs())
        if path.startswith("/jobs/"):
            f = (pipeline.JOBS / path[6:]).resolve()
            if f.is_file() and f.is_relative_to(pipeline.JOBS.resolve()):
                ctype = mimetypes.guess_type(f.name)[0] or "text/plain"
                if ctype.startswith("text/") or f.suffix in (".md", ".log"):
                    ctype = ("text/html" if f.suffix == ".html" else "text/plain") + "; charset=utf-8"
                return self.send(200, f.read_bytes(), ctype)
        self.send(404, {"error": "找不到"})

    def do_POST(self):
        path = unquote(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if body.get("profile") and pipeline.md_error(body["profile"]):
            return self.send(400, {"error": "讀者檔：" + pipeline.md_error(body["profile"])})
        if path == "/api/jobs" and body.get("pdf"):   # 上傳的 PDF：抽成文字，之後跟 .md 一樣
            try:
                body["md"] = pipeline.pdf_to_text(base64.b64decode(body["pdf"]))
            except (RuntimeError, ValueError) as e:
                return self.send(400, {"error": str(e)})
        if path == "/api/jobs" and body.get("md") is not None:   # 上傳的 .md 檔
            if pipeline.md_error(body["md"]):
                return self.send(400, {"error": pipeline.md_error(body["md"])})
            job = pipeline.new_md_job(body["md"], body.get("filename") or "上傳.md", body.get("reader") or "", body.get("draw") or "mermaid")
            if body.get("profile"):
                pipeline.attach_profile(job, body["profile"], body.get("profile_name") or "讀者.md")
            start(job)
            return self.send(200, {"id": job.name})
        if path == "/api/jobs":
            url = (body.get("url") or "").strip()
            if pipeline.url_error(url):
                return self.send(400, {"error": pipeline.url_error(url)})
            job = pipeline.new_job(url, body.get("reader") or "", body.get("source") or "subs", body.get("draw") or "mermaid")
            if body.get("profile"):
                pipeline.attach_profile(job, body["profile"], body.get("profile_name") or "讀者.md")
            start(job)
            return self.send(200, {"id": job.name})
        if path.startswith("/api/jobs/") and path.endswith("/delete"):
            try:
                pipeline.delete_job(path.split("/")[3])
            except RuntimeError as e:
                return self.send(400, {"error": str(e)})
            return self.send(200, {"ok": True})
        if path.startswith("/api/jobs/") and path.endswith("/retry"):
            job = pipeline.JOBS / path.split("/")[3]
            if (job / "status.json").exists() and not pipeline.load(job)["running"]:
                start(job)
                return self.send(200, {"id": job.name})
        self.send(404, {"error": "找不到"})

    def log_message(self, *a):   # 前端每幾秒問一次進度，不要洗版
        pass


if __name__ == "__main__":
    pipeline.JOBS.mkdir(exist_ok=True)
    for f in pipeline.JOBS.glob("*/status.json"):   # 上次關掉伺服器時還在跑的工作：標成中斷，可以按重跑
        st = json.loads(f.read_text(encoding="utf-8"))
        if st.get("running"):
            st.update(running=False, error="伺服器重開，這個工作中斷了；按「重跑」會從沒做完的那一步接下去")
            pipeline.save(f.parent, st)
    print(f"http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
