"""Offline regression checks: no paid API calls, Telegram messages or WordPress writes."""
import json
import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

import generated_images
import bot_app
import pipeline
import qwen_client
import source_fetch
import transcript_source
import utils_text
import video_source
import visual_story


class SourcesTest(unittest.TestCase):
    def test_qwen_image_request_and_download(self):
        response = Mock(status_code=200)
        response.json.return_value = {"output": {"choices": [{"message": {"content": [{"image": "https://cdn.example/result.png"}]}}]}}
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "generated.png"
            def download(url, path):
                Image.new("RGB", (64, 36), "white").save(path)
            with patch.object(generated_images.requests, "post", return_value=response) as post, patch.object(source_fetch, "download", side_effect=download), patch.object(generated_images.config, "QWEN_API_KEY", "test-key"):
                generated_images.generate("Architectural concept, watercolor", dest)
            self.assertTrue(dest.exists())
            request = post.call_args.kwargs
            self.assertEqual(request["headers"]["Authorization"], "Bearer test-key")
            self.assertEqual(request["json"]["parameters"]["n"], 1)
            self.assertEqual(request["json"]["input"]["messages"][0]["content"][0]["text"], "Architectural concept, watercolor")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg unavailable")
    def test_real_ffmpeg_single_pass_and_unknown_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "clip.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc=size=320x180:rate=5:duration=3", "-pix_fmt", "yuv420p", str(source)], check=True, timeout=30)
            with patch.object(video_source, "_download_source", return_value=str(source)) as download:
                frames, interval = visual_story.extract({"duration": 0}, Path(folder) / "scan")
            self.assertEqual(interval, 1)
            self.assertEqual([f["seconds"] for f in frames], [0, 1, 2])
            download.assert_called_once()

    def test_command_routes_text_article_instagram_youtube(self):
        update = SimpleNamespace(effective_message=object(), effective_user=SimpleNamespace(id=1), effective_chat=SimpleNamespace(id=1))
        for source, expected in [("catatan pendek", "text"), ("https://example.com/article", "source_url"),
                                 ("https://www.instagram.com/reel/ABC/", "source_url"), ("https://youtu.be/abcdefghijk", "video_id")]:
            with self.subTest(source=source), patch.object(bot_app, "create_article", new=Mock(return_value=None)) as create, patch.object(bot_app, "start_task", return_value=True), patch.object(bot_app.STATE, "key", return_value="test"):
                asyncio.run(bot_app.cmd_artikel(update, SimpleNamespace(args=source.split())))
                self.assertIn(expected, create.call_args.kwargs)
                self.assertIsNone(create.call_args.kwargs["mode"])

    def test_transcript_noise_and_sparse_speech(self):
        for text in ("[musik]", "[Music] ♪", "halo", "halo " * 500):
            self.assertFalse(transcript_source.quality([{"text": text, "start": 0, "duration": 600}], 600)["adequate"])
        normal = [{"text": "Kita akan membahas cara membuat gambar desain bangunan dengan software CAD untuk proyek arsitektur", "start": i * 10, "duration": 10} for i in range(60)]
        self.assertTrue(transcript_source.quality(normal, 600)["adequate"])
        self.assertTrue(transcript_source.quality([{"text": "Pilih menu gambar kemudian tekan tombol simpan", "duration": 10}], 10)["adequate"])

    def test_sparse_subtitle_still_tries_speech_backend(self):
        poor = {"snippets": [{"text": "[musik]"}]}
        good = {"snippets": [{"text": "Kita belajar menggambar desain arsitektur dengan software CAD dan menyimpan proyek bangunan", "duration": 50}]}
        with patch.object(transcript_source, "_from_api", return_value=poor), patch.object(transcript_source, "_from_ytdlp", return_value=poor), patch.object(transcript_source, "_from_deepgram", return_value=good) as speech:
            self.assertEqual(transcript_source.fetch("abcdefghijk", duration=60), good)
            speech.assert_called_once()

    def test_interval_and_long_video_budget(self):
        self.assertEqual(visual_story.sampling(60), 1)
        self.assertEqual(visual_story.sampling(600), 10)
        self.assertLessEqual(36000 / visual_story.sampling(36000), 120)
        self.assertLessEqual(600 / visual_story.sampling(600, 10), 10)

    def test_chronological_chunks_and_valid_keyframes(self):
        with tempfile.TemporaryDirectory() as folder:
            frames = []
            for i in range(25):
                path = Path(folder) / ("frame_%d.jpg" % i)
                Image.new("RGB", (160, 90), "blue").save(path)
                frames.append({"key": "V%d" % (i + 1), "path": str(path), "label": str(i * 10), "seconds": i * 10})
            replies = [(json.dumps({"notes": "langkah %d" % n, "keyframes": ["UNKNOWN", "V%d" % (1 + n * 12)]}), "fake") for n in range(3)]
            with patch.object(visual_story, "extract", return_value=(frames, 10)), patch.object(qwen_client, "vision", side_effect=replies) as vision:
                result = visual_story.read({"title": "Tutorial"}, folder)
            self.assertEqual(result["chunks"], 3)
            self.assertIn("langkah 2", result["text"])
            self.assertEqual([f["key"] for f in result["selected"]], ["V1", "V13", "V25"])
            self.assertIn("langkah 0", vision.call_args_list[1].args[0])

    def test_instagram_photo_no_video_format(self):
        info = {"title": "Foto CAD", "description": "Kegiatan desain", "formats": [], "thumbnails": [{"url": "https://cdn.example/photo.jpg"}]}
        with tempfile.TemporaryDirectory() as folder, patch.object(source_fetch, "validate_url"), patch("yt_dlp.YoutubeDL") as ydl, patch.object(source_fetch, "download"):
            ydl.return_value.__enter__.return_value.extract_info.return_value = info
            result = source_fetch.instagram("https://www.instagram.com/p/ABC/", folder)
            self.assertEqual(len(result["images"]), 1)
            self.assertEqual(result["videos"], [])
            self.assertTrue(ydl.call_args.args[0]["ignore_no_formats_error"])

    def test_instagram_video_with_unknown_codec(self):
        info = {"formats": [{"url": "https://cdn.example/video.mp4", "ext": "mp4", "height": 720}]}
        self.assertEqual(video_source._best_direct_url(info), "https://cdn.example/video.mp4")

    def test_extract_article_body_not_navigation(self):
        paragraph = "O software CAD permite criar desenhos tecnicos para projetos de engenharia e arquitetura com precisao. "
        raw = ("<html><head><title>Engenharia no Brasil</title></head><body><nav>LOGIN MENU</nav><article><h1>Projetos CAD</h1>" + "".join("<p>%s</p>" % (paragraph * 3) for _ in range(5)) + "</article></body></html>").encode()
        with patch.object(source_fetch, "download", return_value=(raw, "utf-8", "https://example.com/brasil")):
            result = source_fetch.article("https://example.com/brasil")
        self.assertIn("software CAD", result["text"])
        self.assertNotIn("LOGIN MENU", result["text"])
        self.assertEqual(result["title"], "Engenharia no Brasil")

    def test_url_and_private_source(self):
        self.assertEqual(utils_text.extract_source_url("buat https://example.com/artikel. ya"), "https://example.com/artikel")
        self.assertTrue(source_fetch.is_instagram("https://www.instagram.com/reel/abc"))
        self.assertFalse(source_fetch.is_instagram("https://instagram.com.example.com/reel/abc"))
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 80))]):
            with self.assertRaises(source_fetch.SourceError):
                source_fetch.validate_url("https://localhost/a")

    def test_eight_styles_random_regeneration_and_unique_files(self):
        self.assertEqual(len(generated_images.STYLES), 8)
        self.assertEqual(len({style for _, style in generated_images.STYLES}), 8)
        self.assertFalse(any("komik" in label.lower() or "cyberpunk" in label.lower() for label, _ in generated_images.STYLES))
        with tempfile.TemporaryDirectory() as folder:
            draft = {"article": {"title": "Tutorial CAD"}, "work_dir": folder,
                     "images": [{"key": "G1", "origin": "generated", "label": generated_images.STYLES[0][0], "prompt": "old composition"}]}
            def fake_generate(prompt, path):
                Image.new("RGB", (64, 36), "white").save(path)
            with patch.object(qwen_client, "chat_json", return_value=({"concept": "A sculptural hand organizing architectural plans"}, "fake")), patch.object(generated_images, "generate", side_effect=fake_generate) as generate, patch.object(generated_images.secrets, "choice", side_effect=lambda options: options[0]) as choose:
                first = generated_images.random_thumbnail(draft)
                draft["images"].append(first)
                second = generated_images.random_thumbnail(draft)
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(first["key"], "G2")
            self.assertEqual(second["key"], "G3")
            self.assertNotEqual(first["path"], second["path"])
            self.assertNotEqual(first["label"], draft["images"][0]["label"])
            self.assertNotEqual(first["label"], second["label"])
            self.assertEqual(len(choose.call_args_list[0].args[0]), 7)

    def test_failed_regeneration_preserves_featured_and_history(self):
        draft = {"article": {"title": "CAD"}, "images": [{"key": "T1", "role": "featured"}], "history": []}
        with patch.object(generated_images, "random_thumbnail", side_effect=RuntimeError("API unavailable")):
            with self.assertRaises(RuntimeError):
                pipeline.generate_images(draft)
        self.assertEqual(draft["images"], [{"key": "T1", "role": "featured"}])
        self.assertEqual(draft["history"], [])

    def test_regeneration_sets_featured_preserves_previous_and_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            draft = {"id": "thumbnailtest", "article": {"title": "CAD"}, "work_dir": folder,
                     "images": [{"key": "T1", "role": "featured"}], "history": []}
            path = Path(folder) / "new.png"
            Image.new("RGB", (64, 36), "white").save(path)
            entry = {"key": "G1", "path": str(path), "label": "Editorial surealis", "origin": "generated", "prompt": "new idea", "model": "test-model"}
            with patch.object(generated_images, "random_thumbnail", return_value=entry), patch.object(pipeline, "write_markdown"), patch.object(pipeline.drafts, "save"):
                result = pipeline.generate_images(draft)
                self.assertEqual(result["role"], "featured")
                self.assertEqual(draft["images"][0]["role"], "spare")
                self.assertEqual(len(draft["images"]), 2)
                pipeline.undo(draft)
            self.assertEqual(draft["images"], [{"key": "T1", "role": "featured"}])

    def _video_pipeline(self, folder, adequate=True):
        snippets = [{"text": "Kita belajar membuat gambar desain arsitektur memakai software CAD untuk bangunan dan menyimpan berkas", "start": 0, "duration": 50}]
        info = {"video_id": "abcdefghijk", "duration": 60, "title": "Tutorial", "url": "https://youtu.be/abcdefghijk"}
        transcript = {"snippets": snippets} if adequate else transcript_source.TranscriptError("no subtitles")
        with patch.object(pipeline.config, "JOBS_DIR", Path(folder)), patch.object(pipeline.config, "CACHE_DIR", Path(folder)), patch.object(video_source, "probe", return_value=info), patch.object(transcript_source, "fetch", **({"return_value": transcript} if adequate else {"side_effect": transcript})), patch.object(video_source, "grab_frames", return_value=[]) as frames, patch.object(video_source, "download_thumbnail", return_value=None), patch.object(visual_story, "read", return_value={"text": "PENGAMATAN VISUAL: menu simpan", "interval": 1, "frames": 60, "chunks": 5, "selected": []}) as visual, patch.object(pipeline, "_links_for", return_value={}), patch.object(pipeline.article_generator, "write", return_value={"title": "Desain CAD"}), patch.object(pipeline.sipira, "cta_link", return_value={"url": "https://example.com", "code": "abc"}), patch.object(pipeline, "write_markdown"), patch.object(pipeline.drafts, "save"):
            with patch.object(pipeline, "generate_images") as thumbnail:
                draft = pipeline.create(video_id="abcdefghijk", mode="article")
                thumbnail.assert_called_once()
            if adequate:
                frames.assert_called_once()
                visual.assert_not_called()
            else:
                visual.assert_called_once()
                frames.assert_not_called()
                self.assertIn("PENGAMATAN VISUAL", pipeline.material(draft))

    def test_normal_speech_keeps_existing_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            self._video_pipeline(folder, adequate=True)

    def test_missing_transcript_uses_vision(self):
        with tempfile.TemporaryDirectory() as folder:
            self._video_pipeline(folder, adequate=False)


if __name__ == "__main__":
    unittest.main()
