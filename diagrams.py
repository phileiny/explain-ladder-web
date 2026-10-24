"""第 2 層：把 <job>/2_圖解.md 的每一張圖（Mermaid 或表格）出成 <job>/圖/圖N.png（已存在的不重出）
預設用 Chrome 直接渲染 Mermaid 和表格（免費）；加 --gemini 才交給 Gemini Pro 出資訊圖（要花錢）
用法：python diagrams.py <job 資料夾> [--gemini]（python 要有 Pillow；Gemini 模式還要 google-genai、python-dotenv）
改自 ~/sides/story/短影音行銷之路/tools/gen_diagrams.py（那邊踩過的坑都留著：先把 Mermaid 拆成方塊和箭頭清單、先用 Chrome 渲染版面當參考圖）"""
import html, json, pathlib, re, subprocess, sys, time

MODEL = "gemini-3-pro-image"
NUM = "一二三四五六七八九"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

STYLE = """Make ONE clean, flat, modern infographic, aspect ratio {aspect}.
⭐ ALL TEXT IS TRADITIONAL CHINESE (繁體中文). Copy every label EXACTLY, character by character, from the content below — no simplified characters, no extra words, no missing words, no invented numbers, no English unless it is in the content.
Title at the top, large, exactly this text and NO quotation marks or brackets added around it: {title}
Never print code syntax: no node IDs (A, B1…), no [ ] {{ }} brackets, no arrows written as text.
Visual style: off-white background (#F4F6F8); dark ink text (#151A21); cobalt blue (#1F4FD1) for boxes, arrows and lines; warm yellow (#FFD34D) only to highlight the single most important box or answer; grey (#5B6573) for small notes.
Rounded rectangles for steps, diamonds for yes/no questions, arrows labelled 是／否 exactly as given. Generous white space, aligned grid, large readable type (it will be read on a phone).
No photos, no people, no 3D, no logos, no emoji, no decorative clutter.
⭐ If the content is a list of boxes and arrows: draw EVERY arrow in the list, including loop-backs — check each one once.
⭐ If the content is a Markdown table: draw it as a clean table or card grid with the same rows and columns — NO arrows between columns (the columns are not steps).
Below is the content — keep its structure and its exact words.
---
{body}
---
{note}"""

NODE = re.compile(r'([A-Za-z0-9_]+)\s*(\(\(.*?\)\)|\(\[.*?\]\)|\[\[.*?\]\]|\[.*?\]|\{.*?\}|\(.*?\))')
EDGE = re.compile(r'\s*(-->|-\.->|==>|---)\s*(?:\|([^|]*)\|)?\s*|\s*--\s*([^-][^>]*?)\s*-->\s*|\s*-\.\s*([^.]+?)\s*\.->\s*')

def mermaid_spec(code):
    """Mermaid → 方塊清單＋箭頭清單（純文字，模型不必讀語法；直接給原始碼時箭頭常畫錯）"""
    labels, shapes, edges, groups, cur = {}, {}, [], [], None
    def lab(tok):
        m = NODE.match(tok.strip())
        if m:
            i, raw = m.group(1), m.group(2)
            shapes[i] = "diamond (yes/no question)" if raw.startswith("{") else "rounded box"
            labels[i] = raw.strip("[](){}").replace("<br>", " / ").replace('"', "")
            return i
        return tok.strip()
    for line in code.splitlines():
        t = line.strip()
        if not t or t.startswith(("flowchart", "graph", "%%", "classDef", "class ", "style ", "linkStyle", "direction")): continue
        if t.startswith("subgraph"):
            title = t[8:].strip(); m = re.match(r'(\S+?)\s*(\[.*\])$', title)   # 群組代號可能是中文
            gid, gtitle = (m.group(1), m.group(2).strip("[]\"")) if m else (title, title.strip('"'))
            labels[gid] = gtitle; cur = [gtitle, []]; groups.append(cur); continue
        if t == "end": cur = None; continue
        parts = EDGE.split(t)
        # parts: node, op, pipe-label, dash-label, dot-label, node, ...
        nodes = [parts[k] for k in range(0, len(parts), 5)]
        ids = [lab(n) for n in nodes if n and n.strip()]
        if cur is not None: cur[1] += [i for i in ids if i not in cur[1]]
        for k in range(len(ids) - 1):
            g = parts[5 * k + 1: 5 * k + 5]
            edges.append((ids[k], ids[k + 1], next((x.strip().strip('"') for x in g[1:] if x and x.strip()), ""), "dotted" if g[0] and "." in g[0] else "solid"))
    name = lambda i: f'"{labels.get(i, i)}"'
    out = ["BOXES (draw each once, with exactly the text between the straight double quotes — do not draw the double quotes; ' / ' is a line break inside the box):"]
    out += [f"- {name(i)} — {shapes[i]}" for i in shapes]
    for title, members in groups:
        out.append(f'GROUP (a light frame) labelled "{title}" contains only: ' + "、".join(name(i) for i in members if i in shapes))
    out.append(f"ARROWS — draw EXACTLY these {len(edges)} arrows and NO OTHERS (no extra lines, no shared trunk lines that make one arrow look like it goes to two places):")
    out += [f"{n}. {name(a)} → {name(b)}" + (f'  labelled "{l}"' if l else "") + ("  (dotted)" if st == "dotted" else "") for n, (a, b, l, st) in enumerate(edges, 1)]
    return "\n".join(out)

def diagrams(text):
    """回傳 [(n, 標題, 給模型的內容, 圖下說明, Mermaid 原始碼或 "")]"""
    out = []
    for m in re.finditer(r"^## 圖(\S)\s*(.+?)\n(.*?)(?=^## 圖|\Z)", text, re.S | re.M):
        n = NUM.index(m.group(1)) + 1 if m.group(1) in NUM else int(m.group(1))
        body = m.group(3)
        block = re.search(r"```mermaid\n(.*?)```", body, re.S)
        table = "\n".join(l for l in body.splitlines() if l.startswith("|"))
        content = (mermaid_spec(block.group(1)) + (f"\nALSO draw this small table under the diagram, same words:\n{table}" if table else "")) if block else table
        note = re.sub(r"```mermaid.*?```", "", body, flags=re.S)
        note = "\n".join(l for l in note.splitlines() if l.strip() and not l.startswith(("|", "!", "<")))
        out.append((n, m.group(2).strip(), content.strip(), note.strip(), block.group(1) if block else ""))
    return out

def table_html(md):
    """Markdown 表格 → HTML 表格（分隔列 |---| 丟掉，第一列當表頭）"""
    rows = [l.strip().strip("|") for l in md.splitlines() if l.strip().startswith("|")]
    rows = [r for r in rows if not re.fullmatch(r"[\s:|-]+", r)]
    cells = [[html.escape(c.strip()) for c in r.split("|")] for r in rows]
    if not cells: return ""
    head = "<tr>" + "".join(f"<th>{c}</th>" for c in cells[0]) + "</tr>"
    return "<table>" + head + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in cells[1:]) + "</table>"

def mermaid_pre(code):
    return ('<pre class="mermaid" style="font-size:22px">' + code.replace("<", "&lt;").replace("&lt;br>", "<br>").replace("&lt;br/>", "<br/>") + '</pre>'
        '<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>'
        '<script>mermaid.initialize({startOnLoad:true,theme:"neutral",themeVariables:{xyChart:{plotColorPalette:"#1F4FD1"}},flowchart:{htmlLabels:true}})</script>')

def page_png(inner, dst, border=0):
    """用 Chrome 無頭模式截一頁白底 HTML，裁掉四周空白"""
    from PIL import Image, ImageOps
    page = dst.with_suffix(".html")
    page.write_text('<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#fff;color:#151A21;font-family:"PingFang TC","Noto Sans TC",sans-serif}'
        'h1{font-size:40px;margin:0 0 28px}table{border-collapse:collapse;font-size:26px}'
        'th,td{border:1px solid #c9d0da;padding:12px 20px;text-align:left}th{background:#eef2f7}</style>'
        '<body><div style="display:inline-block;padding:4px">' + inner + '</div>', encoding="utf-8")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=2400,1600", "--force-device-scale-factor=2",
                    "--virtual-time-budget=8000", f"--screenshot={dst}", page.as_uri()], check=True, capture_output=True)
    page.unlink()
    im = Image.open(dst).convert("RGB"); bbox = Image.eval(im.convert("L"), lambda v: 255 - v).getbbox()
    if bbox: im = im.crop(bbox)
    (ImageOps.expand(im, border=border, fill="white") if border else im).save(dst)
    return dst

def mermaid_png(code, dst):
    """用 mermaid.js 渲染原始碼 → 版面參考圖（Gemini 模式只當結構依據）"""
    return page_png(mermaid_pre(code), dst)

def free_png(folder, job):
    """免費模式的成品圖：標題＋Mermaid 圖＋表格，全部由 Chrome 渲染"""
    n, title, body, note, code = job
    dst = folder / f"圖{n}.png"
    if dst.exists(): return f"⏭  圖{n}"
    table = "\n".join(l for l in body.splitlines() if l.startswith("|"))
    try:
        page_png(f"<h1>{html.escape(title)}</h1>" + (mermaid_pre(code) if code else "") + table_html(table), dst, border=40)
        return f"✅ 圖{n}（Mermaid）"
    except Exception as e:
        return f"❌ 圖{n}: {e}"

def run(client, folder, job):
    from io import BytesIO
    from google.genai import types
    from PIL import Image
    n, title, body, note, code = job
    dst = folder / f"圖{n}.png"
    if dst.exists(): return f"⏭  圖{n}"
    note = "Caption under the diagram, small grey text, every line below exactly as written, NO quotation marks added:\n" + note if note else ""
    t, msg = time.time(), ""
    for attempt in range(3):
        try:
            aspect, lead = "16:9", []
            if code and pathlib.Path(CHROME).exists():
                ref = mermaid_png(code, folder / f"_ref{n}.png")
                w, h = Image.open(ref).size; r_ = w / h
                aspect = "16:9" if r_ > 1.4 else "4:3" if r_ > 1.1 else "1:1" if r_ > 0.85 else "3:4" if r_ > 0.6 else "9:16"   # 照參考圖的比例，不要重排
                lead = [Image.open(ref), "⭐ THE PICTURE ABOVE IS THE CORRECT DIAGRAM: redraw it in the style below, keeping EVERY box, EVERY arrow (start box, end box, direction, label) and the overall layout exactly as in the picture. Do not add, remove, merge or re-route any arrow.\n"]
            prompt = STYLE.format(aspect=aspect, title=title, body=body, note=note)
            r = client.models.generate_content(model=MODEL, contents=lead + [prompt],
                    config=types.GenerateContentConfig(response_modalities=["IMAGE"],
                        image_config=types.ImageConfig(aspect_ratio=aspect, image_size="2K")))
            for part in r.candidates[0].content.parts:
                if part.inline_data:
                    Image.open(BytesIO(part.inline_data.data)).convert("RGB").save(dst)
                    return f"✅ 圖{n}  {time.time()-t:.0f}s"
            msg = r.candidates[0].finish_reason
        except Exception as e:
            msg = e
        time.sleep(5 * (attempt + 1))
    return f"❌ 圖{n}: {msg}"

if __name__ == "__main__":
    job = pathlib.Path(sys.argv[1])
    folder = job / "圖"; folder.mkdir(exist_ok=True)
    jobs = diagrams((job / "2_圖解.md").read_text(encoding="utf-8"))
    if "--gemini" not in sys.argv[2:]:
        print(f"{len(jobs)} 張，Mermaid（免費）")
        for j in jobs: print(free_png(folder, j), flush=True)
        sys.exit(0)
    from concurrent.futures import ThreadPoolExecutor
    from dotenv import load_dotenv
    from google import genai
    # GEMINI_API_KEY：repo 根目錄的 .env，或 local.json 的 "env" 指到的檔
    root = pathlib.Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    if (root / "local.json").exists():
        env = json.loads((root / "local.json").read_text(encoding="utf-8")).get("env")
        if env: load_dotenv(pathlib.Path(env).expanduser())
    client = genai.Client()   # 單一 client，不要在迴圈裡重建（會被回收）
    print(f"{len(jobs)} 張，模型 {MODEL}")
    with ThreadPoolExecutor(4) as ex:
        for msg in ex.map(lambda j: run(client, folder, j), jobs): print(msg, flush=True)
