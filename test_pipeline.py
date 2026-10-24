"""python3 -m unittest test_pipeline"""
import unittest

import diagrams, pipeline


class Url(unittest.TestCase):
    def test_accepts_youtube_and_bilibili(self):
        for u in ("https://www.youtube.com/watch?v=E7qB_p1D0Xk", "https://youtu.be/E7qB_p1D0Xk",
                  "https://www.bilibili.com/video/BV1xx411c7mD", "https://b23.tv/abc123"):
            self.assertTrue(pipeline.valid_url(u), u)

    def test_rejects_others(self):
        for u in ("", "youtube.com/watch?v=x", "https://example.com/watch?v=x", "https://notyoutube.com/x", "file:///etc/passwd"):
            self.assertFalse(pipeline.valid_url(u), u)

    SHOW = "https://podcasts.apple.com/tw/podcast/%E8%84%91%E6%94%BE%E7%94%B5%E6%B3%A2/id1661644635"

    def test_apple_podcast_episode_is_accepted(self):
        self.assertEqual(pipeline.url_error(self.SHOW + "?i=1000712345678"), "")
        self.assertEqual(pipeline.url_error("https://youtu.be/E7qB_p1D0Xk"), "")

    def test_apple_podcast_show_asks_for_an_episode_link(self):
        self.assertIn("單集", pipeline.url_error(self.SHOW))

    def test_other_sites_are_refused(self):
        self.assertIn("只收", pipeline.url_error("https://example.com/x"))

    def test_apple_ids(self):
        self.assertEqual(pipeline.apple_ids(self.SHOW + "?l=en&i=1000712345678"), ("1661644635", "1000712345678"))
        self.assertEqual(pipeline.apple_ids(self.SHOW), ("1661644635", None))
        self.assertIsNone(pipeline.apple_ids("https://youtu.be/x"))


class ApplePodcast(unittest.TestCase):
    RESULTS = [
        {"wrapperType": "track", "kind": "podcast", "collectionName": "脑放电波", "artistName": "托马斯白"},
        {"wrapperType": "podcastEpisode", "trackId": 111, "trackName": "別集", "episodeUrl": "https://x/a.mp3"},
        {"wrapperType": "podcastEpisode", "trackId": 222, "trackName": "WWDC26", "collectionName": "脑放电波",
         "trackTimeMillis": 3619000, "description": "說明", "episodeUrl": "https://x/b.mp3"},
    ]

    def test_picks_the_episode_by_id(self):
        ep = pipeline.apple_pick(self.RESULTS, "222")
        self.assertEqual((ep["title"], ep["uploader"], ep["duration"], ep["audio"]), ("WWDC26", "脑放电波", 3619, "https://x/b.mp3"))
        self.assertEqual(ep["description"], "說明")

    def test_missing_episode_says_so(self):
        with self.assertRaises(RuntimeError):
            pipeline.apple_pick(self.RESULTS, "999")


class Subs(unittest.TestCase):
    def test_manual_chinese_first_traditional_before_simplified(self):
        info = {"subtitles": {"en": [], "zh-Hans": [], "zh-Hant": []}}
        self.assertEqual(pipeline.pick_subs(info), ("zh-Hant", False))

    def test_manual_english_beats_machine_translated_chinese(self):
        info = {"subtitles": {"en-GB": []}, "automatic_captions": {"zh-Hant-en-GB": []}}
        self.assertEqual(pipeline.pick_subs(info), ("en-GB", False))

    def test_auto_captions_only_in_original_language(self):
        self.assertEqual(pipeline.pick_subs({"language": "en", "automatic_captions": {"zh-Hant": [], "en": []}}), ("en", True))
        self.assertEqual(pipeline.pick_subs({"automatic_captions": {"zh-Hant": [], "ja-orig": []}}), ("ja-orig", True))
        self.assertIsNone(pipeline.pick_subs({"automatic_captions": {"zh-Hant": [], "en": []}}))

    def test_uploaded_subs_in_another_language_are_translations(self):
        self.assertIsNone(pipeline.pick_subs({"language": "zh", "subtitles": {"en-GB": []}, "automatic_captions": {"en-GB": []}}))
        self.assertEqual(pipeline.pick_subs({"language": "zh-CN", "subtitles": {"en": [], "zh-Hans": []}}), ("zh-Hans", False))

    def test_bilibili_danmaku_is_not_a_subtitle(self):
        self.assertIsNone(pipeline.pick_subs({"subtitles": {"danmaku": []}}))


class Vtt(unittest.TestCase):
    def test_strips_cues_tags_and_repeats_and_marks_time(self):
        vtt = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000
Hello <c>there</c>

00:00:03.000 --> 00:00:05.000
Hello there

00:05:10.000 --> 00:05:12.000 align:start
&lt;b&gt;Tom &amp; Jerry&lt;/b&gt;

01:02:03.000 --> 01:02:05.000
The end
"""
        self.assertEqual(pipeline.vtt_to_text(vtt),
                         "[0:00:01]\nHello there\n\n[0:05:10]\nTom & Jerry\n\n[1:02:03]\nThe end")


class Diagrams(unittest.TestCase):
    MD = """# 圖解

## 圖一　先測再放大
```mermaid
flowchart TD
  A[拍三支] --> B{哪支有反應？}
  B -->|有| C[放大那一支]
  B -->|沒有| A
```
先丟三個方向，再決定錢花在哪。

## 圖二　三種收費
| 做法 | 賣的是 |
|---|---|
| 按人頭 | 過程 |
| 按成果 | 結果 |
"""

    def test_splits_mermaid_and_table(self):
        d = diagrams.diagrams(self.MD)
        self.assertEqual([(n, title) for n, title, *_ in d], [(1, "先測再放大"), (2, "三種收費")])
        self.assertIn('3. "哪支有反應？" → "拍三支"  labelled "沒有"', d[0][2])
        self.assertIn("draw EXACTLY these 3 arrows", d[0][2])
        self.assertEqual(d[0][3], "先丟三個方向，再決定錢花在哪。")
        self.assertTrue(d[0][4].startswith("flowchart TD"))
        self.assertTrue(d[1][2].startswith("| 做法 | 賣的是 |"))
        self.assertEqual(d[1][4], "")

    def test_table_html_keeps_cells_and_drops_separator(self):
        html = diagrams.table_html("| 做法 | 賣的是 |\n|---|---|\n| 按人頭 | 過程 |")
        self.assertIn("<th>做法</th><th>賣的是</th>", html)
        self.assertIn("<td>按人頭</td><td>過程</td>", html)
        self.assertNotIn("---", html)


def tiny_pdf(text):
    """最小的一頁 PDF；text 空字串就是沒有文字的 PDF（像掃描檔）"""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


class Pdf(unittest.TestCase):
    def test_pdf_text_is_extracted(self):
        self.assertIn("Weekly report about on-prem agents", pipeline.pdf_to_text(tiny_pdf("Weekly report about on-prem agents")))

    def test_pdf_without_text_says_so(self):
        with self.assertRaises(RuntimeError) as e:
            pipeline.pdf_to_text(tiny_pdf(""))
        self.assertIn("掃描", str(e.exception))


class HouseStyle(unittest.TestCase):
    def test_house_style_goes_into_the_head_once(self):
        html = pipeline.apply_house_style("<!doctype html><html><head><title>T</title></head><body></body></html>")
        self.assertEqual(html.count("星智未來版型"), 1)
        self.assertLess(html.index("星智未來版型"), html.index("</head>"))
        self.assertIn("fonts.googleapis.com", html)
        self.assertEqual(pipeline.apply_house_style(html), html)

    def test_house_style_without_head(self):
        html = pipeline.apply_house_style("<div class='wrap'>內容</div>")
        self.assertTrue(html.startswith("<link") or html.startswith("<style"))
        self.assertIn("內容", html)

    def test_page_prompt_has_design_brief_not_fixed_tabs(self):
        p = pipeline.page_prompt("圖說", "第一層", "第二層")
        self.assertNotIn("「重點」「圖解」「動手試」「小測驗」", p)
        self.assertIn(".card", p)          # 版型的 class 說明有附上
        self.assertIn("先判斷", p)


class NewJob(unittest.TestCase):
    def setUp(self):
        import pathlib, tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.old, pipeline.JOBS = pipeline.JOBS, pathlib.Path(self.tmp.name)

    def tearDown(self):
        pipeline.JOBS = self.old
        self.tmp.cleanup()

    def test_draws_with_free_mermaid_by_default(self):
        self.assertEqual(pipeline.load(pipeline.new_job("https://youtu.be/x"))["draw"], "mermaid")

    def test_md_file_becomes_the_transcript(self):
        job = pipeline.new_md_job("# 台灣週報\n\n內容", "taiwan.md")
        st = pipeline.load(job)
        self.assertEqual((st["title"], st["source"], st["url"]), ("台灣週報", "md", ""))
        self.assertEqual((job / "逐字稿.txt").read_text(encoding="utf-8"), "# 台灣週報\n\n內容")
        self.assertTrue((job / "影片說明.txt").exists())
        self.assertIn("taiwan.md", st["note"])

    def test_md_meta_says_it_is_a_text_file_not_a_video(self):
        meta = pipeline.meta_text(pipeline.load(pipeline.new_md_job("# 台灣週報\n內容", "taiwan.md")))
        self.assertIn("上傳的文字檔（taiwan.md）", meta)
        self.assertIn("章節", meta)
        for word in ("頻道：", "分鐘", "連結："):
            self.assertNotIn(word, meta)

    def test_video_meta_keeps_channel_length_and_link(self):
        st = {"title": "T", "uploader": "C", "duration": 3600, "url": "https://youtu.be/x", "note": ""}
        meta = pipeline.meta_text(st)
        self.assertIn("頻道：C", meta)
        self.assertIn("長度：60 分鐘", meta)
        self.assertIn("連結：https://youtu.be/x", meta)

    def test_profile_goes_into_the_reader_text(self):
        job = pipeline.new_job("https://youtu.be/x")
        pipeline.attach_profile(job, "# 讀者檔\n不要壓縮訊息", "讀者檔.md")
        st = pipeline.load(job)
        self.assertEqual(st["profile"], "讀者檔.md")
        text = pipeline.reader_text(job, st)
        self.assertIn("不要壓縮訊息", text)
        self.assertIn(st["reader"], text)

    def test_reader_text_without_profile_is_the_reader(self):
        job = pipeline.new_job("https://youtu.be/x", "國中生")
        self.assertEqual(pipeline.reader_text(job, pipeline.load(job)), "國中生")

    def test_md_title_falls_back_to_file_name(self):
        self.assertEqual(pipeline.load(pipeline.new_md_job("沒有標題的內容", "週報 10-16.md"))["title"], "週報 10-16")

    def test_md_error(self):
        self.assertIn("空", pipeline.md_error("  \n"))
        self.assertIn("太大", pipeline.md_error("字" * 2_000_001))
        self.assertEqual(pipeline.md_error("內容"), "")

    def test_delete_moves_a_finished_job_to_the_trash(self):
        import pathlib, tempfile
        trash = tempfile.TemporaryDirectory()
        old, pipeline.TRASH = pipeline.TRASH, pathlib.Path(trash.name)
        try:
            job = pipeline.new_job("https://youtu.be/x")
            st = pipeline.load(job); st["running"] = False; pipeline.save(job, st)
            pipeline.delete_job(job.name)
            self.assertFalse(job.exists())
            self.assertTrue((pipeline.TRASH / f"explain-ladder-{job.name}" / "status.json").exists())
        finally:
            pipeline.TRASH = old
            trash.cleanup()

    def test_delete_refuses_a_running_job(self):
        job = pipeline.new_job("https://youtu.be/x")
        with self.assertRaises(RuntimeError):
            pipeline.delete_job(job.name)
        self.assertTrue(job.exists())

    def test_delete_refuses_a_bad_id(self):
        for bad in ("../x", "", "20261016-120507/.."):
            with self.assertRaises(RuntimeError):
                pipeline.delete_job(bad)

    def test_keeps_gemini_only_when_asked(self):
        import time
        self.assertEqual(pipeline.load(pipeline.new_job("https://youtu.be/x", draw="gemini"))["draw"], "gemini")
        time.sleep(1)   # 工作資料夾以秒命名
        self.assertEqual(pipeline.load(pipeline.new_job("https://youtu.be/x", draw="亂填"))["draw"], "mermaid")


if __name__ == "__main__":
    unittest.main()
