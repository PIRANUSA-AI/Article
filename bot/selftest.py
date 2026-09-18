import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import article_generator
import bot_app
import config
import drafts
import humanizer
import image_picker
import pipeline
import telegram_view
import transcript_source
import utils_text
import video_source
import wxr_builder

print("imports ok")

assert utils_text.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=x") == "dQw4w9WgXcQ"
assert utils_text.extract_video_id("youtu.be/abc123DEF45") == "abc123DEF45"
assert utils_text.extract_video_id("tolong transkrip https://m.youtube.com/shorts/aaaaaaaaaaa") == "aaaaaaaaaaa"
assert utils_text.extract_video_id("halo apa kabar") is None
assert video_source.parse_timestamp("3:20") == 200
assert video_source.parse_timestamp("1:02:03") == 3723
points = video_source._sample_points(600, 10)
assert len(points) == 10 and points[0] >= 40 and points[-1] <= 560, points
print("url, timestamp, sampling ok")

snips = [
    {"start": 0.0, "duration": 2.0, "text": "Halo semuanya, hari ini kita bahas BIM cloud."},
    {"start": 2.0, "duration": 2.0, "text": "Halo semuanya, hari ini kita bahas BIM cloud."},
    {"start": 6.0, "duration": 2.0, "text": "IFC dipakai untuk pertukaran data lintas disiplin."},
]
assert transcript_source.as_plain_text(transcript_source._dedupe(snips)).count("Halo semuanya") == 1
assert transcript_source.timed_lines(snips, "IFC")[0][0] == 6.0
print("transcript helpers ok")

cases = {
    "Koordinasi antar divisi—desain dan lapangan—jadi rapi.": "Koordinasi antar divisi, desain dan lapangan, jadi rapi.",
    "Direkam [01:10–01:53] lalu disimpan; selesai.": "Direkam lalu disimpan. Selesai.",
    "Dipakai sehari-hari oleh orang-orang non-teknis se-Indonesia tahun 1990-an.": "Dipakai sehari hari oleh orang orang nonteknis seluruh Indonesia tahun 1990an.",
    "Periode 2024-2025 pakai qwen3.8-max dan e-commerce.": "Periode 2024 sampai 2025 pakai qwen3.8-max dan e-commerce.",
    "“Kutipan” … \U0001F680 oke": '"Kutipan"... oke',
}
for source, expected in cases.items():
    got = humanizer.sanitize(source)
    assert got == expected, (source, got)
assert humanizer.ai_smell("Fitur ini merupakan solusi terbaik") == ["merupakan", "solusi terbaik"]
assert "Mode tersemat" in humanizer.rules()
print("humanizer ok")

assert article_generator.too_similar("Cara Kasih Catatan di Drawing Pakai Suara", "Cara Kasih Catatan di Drawing Pakai Suara dengan Smart Voice ZWCAD")
assert not article_generator.too_similar("Revisi gambar kerja salah paham terus? Coba rekam suaramu", "Cara Kasih Catatan di Drawing Pakai Suara dengan Smart Voice ZWCAD")
print("title similarity ok")

raw = {
    "title_options": [
        {"tone": "edukatif", "title": "Cara kerja BIM di proyek arsitektur kecil", "subtitle": "Langkah praktis—tanpa software mahal."},
        {"tone": "penasaran", "title": "Kenapa Arsitek Perlu BIM", "subtitle": "Salinan judul sumber."},
        {"tone": "waspada", "title": "Tiga kesalahan tim yang pindah ke BIM", "subtitle": "Kesalahan yang bikin revisi dobel."},
        {"tone": "kontras", "title": "Gambar 2D lawan model BIM untuk revisi", "subtitle": "Mana yang lebih cepat saat klien berubah pikiran."},
        {"tone": "terbalik", "title": "BIM bikin kerja lambat? Justru sebaliknya", "subtitle": "Anggapan yang sering muncul di awal adopsi."},
    ],
    "recommended": 4,
    "summary": {"text": "Model BIM menyimpan data elemen; revisi menyebar otomatis.", "points": ["Data elemen", "- IFC untuk tukar data"]},
    "sections": [
        {"heading": "Data, bukan garis", "image": "F1", "blocks": [
            {"type": "paragraph", "text": "Model BIM menyimpan **data elemen** [02:10]."},
            {"type": "steps", "items": ["Buka model", "Ekspor IFC"]},
            {"type": "quote", "text": "IFC dipakai untuk pertukaran data lintas disiplin.", "by": "Piranusa ID"},
        ]},
        {"heading": "Revisi lebih singkat", "image": "F1", "blocks": [{"type": "callout", "text": "Simpan versi sebelum ekspor."}]},
        {"heading": "Kolaborasi", "image": "ZZ", "blocks": [{"type": "list", "items": ["BIMcloud", "Teamwork"]}]},
    ],
    "conclusion": {"heading": "Jadi, perlu pindah?", "paragraphs": ["Kalau revisi sering, iya."]},
    "cta": "Klik ikon WhatsApp di halaman ini untuk ngobrol soal BIM dengan tim Piranusa.",
    "glossary": [{"term": "IFC", "definition": "Format terbuka pertukaran data bangunan."}],
    "excerpt": "Ringkasan soal manfaat BIM pada proyek arsitektur kecil.",
    "focus_keyword": "BIM arsitektur",
    "slug": "bim untuk arsitek",
    "category": "BIM",
    "tags": ["BIM", "IFC"],
}
article = article_generator.normalize(raw, "video", ["F1", "F2"], 2)
article["title_options"] = article_generator._filter_titles(article["title_options"], "Kenapa Arsitek Perlu BIM")
assert len(article["title_options"]) == 4
article_generator.apply_title(article, article_generator._recommended_index(raw, article["title_options"]))
assert article["tone"] == "terbalik", article["tone"]
assert [s["image"] for s in article["sections"]] == ["F1", None, None]
assert article["slug"] == "bim-untuk-arsitek"
article["_smell"] = 0
for path, _text in article_generator._prose_fields(article):
    current = article
    for key in path:
        current = current[key]
    article_generator._set(article, path, humanizer.sanitize(current))
assert article["summary"]["points"][1] == "IFC untuk tukar data"
assert "[02:10]" not in article["sections"][0]["blocks"][0]["text"]
print("article normalize ok")

img_dir = config.DATA_DIR / "_selftest"
img_dir.mkdir(parents=True, exist_ok=True)
from PIL import Image, ImageDraw

sample = img_dir / "frame.jpg"
canvas = Image.new("RGB", (1280, 720), (30, 60, 90))
pen = ImageDraw.Draw(canvas)
for x in range(0, 1280, 40):
    pen.line([(x, 0), (1280 - x, 720)], fill=(220, 220, 220), width=2)
canvas.save(sample)
blank = img_dir / "blank.jpg"
Image.new("RGB", (1280, 720), (4, 4, 4)).save(blank)
kept = image_picker.prefilter([{"path": sample, "seconds": 10}, {"path": sample, "seconds": 20}, {"path": blank, "seconds": 30}])
assert len(kept) == 1, kept
print("image prefilter ok")

draft = {
    "id": "selftest",
    "owner": "0:0",
    "kind": "video",
    "work_dir": str(img_dir),
    "source": {"type": "video", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Kenapa Arsitek Perlu BIM", "channel": "Piranusa ID", "duration": 640},
    "article": article,
    "images": [
        {"key": "T1", "origin": "thumbnail", "path": str(sample), "width": 1280, "height": 720, "alt": "Thumbnail", "caption": "", "role": "featured", "note": {}},
        {"key": "F1", "origin": "frame", "label": "02:10", "path": str(sample), "width": 1280, "height": 720, "alt": "Panel IFC", "caption": "Menu ekspor IFC", "role": "spare", "note": {"info_score": 8, "kind": "layar_aplikasi"}},
        {"key": "F2", "origin": "frame", "label": "04:00", "path": str(sample), "width": 1280, "height": 720, "alt": "Lain", "caption": "", "role": "spare", "note": {}},
    ],
    "wp": {},
    "history": [],
}
(img_dir / "material.txt").write_text("bahan", encoding="utf-8")

content = wxr_builder.render_content(draft, {"F1": {"id": 55, "src": "https://x.test/a.jpg", "alt": "Panel IFC", "caption": "Menu ekspor IFC"}})
assert content.count("wp:image {") == 1
assert "pipSubtitle" in content and "pipSummary" in content and "pipCta" in content
assert "wp:embed" in content and "Glosarium" in content
assert '<figure class="wp-block-table pipGlossary has-small-font-size">' in content and "<td>IFC</td>" in content
linked = dict(draft, article=dict(article))
linked["article"]["_links"] = {"internal": [{"title": "Artikel BIM", "url": "https://www.piranusa.com/artikel-bim/"}], "external": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]}
linked["article"]["sections"] = [dict(s, blocks=list(s["blocks"])) for s in article["sections"]]
linked["article"]["sections"][0]["blocks"].append({"type": "paragraph", "text": "Lihat [panduan BIM](https://www.piranusa.com/artikel-bim/) dan [video aslinya](https://www.youtube.com/watch?v=dQw4w9WgXcQ) serta [palsu](https://contoh.test/x)."})
article_generator.enforce_links(linked["article"])
assert article_generator.count_links(linked["article"]) == {"internal": 1, "external": 1}
linked_html = wxr_builder.render_content(linked, {})
assert '<a href="https://www.piranusa.com/artikel-bim/">panduan BIM</a>' in linked_html
assert 'target="_blank" rel="noreferrer noopener">video aslinya</a>' in linked_html and "contoh.test" not in linked_html
article["seo_title"] = ""
article["focus_keyword"] = "BIM arsitektur"
article_generator._fix_seo_title(article)
assert article["seo_title"].startswith("BIM arsitektur") and len(article["seo_title"]) <= 60, article["seo_title"]
report = article_generator.seo_report(article, "bim-arsitektur-kecil")
assert report["in_slug"] and report["seo_title_start"]
long_meta = article_generator.trim_meta("kata " * 50)
assert len(long_meta) <= 156 and long_meta.endswith("kata.")
assert article_generator._prefer_keyword([{"title": "Judul lain"}, {"title": "Panduan BIM arsitektur kecil"}], "BIM arsitektur", 0) == 1
assert '<!-- wp:list {"ordered":true} -->' in content
assert "<strong>data elemen</strong>" in content
assert "Catatan metodologi" not in content and "Sumber" not in content
first_heading = content.index("Data, bukan garis")
assert content.index("wp:image {") > first_heading
print("render ok")

package = pipeline.build_files(draft, "")
root = ET.parse(package["xml_path"]).getroot()
items = root.find("channel").findall("item")
WP = "{http://wordpress.org/export/1.2/}"
assert len(items) == 3, len(items)
assert items[0].findtext(WP + "post_type") == "post"
meta = {m.findtext(WP + "meta_key"): m.findtext(WP + "meta_value") for m in items[0].findall(WP + "postmeta")}
assert meta["_thumbnail_id"] == "10001" and meta["_yoast_wpseo_metadesc"]
assert all(i.findtext(WP + "post_type") == "attachment" for i in items[1:])
with zipfile.ZipFile(package["zip_path"]) as archive:
    names = archive.namelist()
assert sum(1 for n in names if n.startswith("wp-content/uploads/")) == 2, names
print("wxr ok:", Path(package["xml_path"]).name, package["words"], "kata")

drafts.save(draft)
drafts.remember_message("selftest", 1, 2)
assert drafts.for_message(1, 2) == "selftest"
pipeline.choose_title(draft, 0)
assert draft["article"]["tone"] == "edukatif"
assert pipeline.undo(draft) == "ganti judul"
assert draft["article"]["tone"] == "terbalik"
pipeline.set_featured(draft, "F1")
assert draft["article"]["sections"][0]["image"] is None
assert [i["key"] for i in wxr_builder.ordered_images(draft)] == ["F1"]
pipeline.undo(draft)
print("draft ops ok")

chunks = telegram_view.preview_chunks(draft)
assert chunks and all(len(c) <= telegram_view.LIMIT for c in chunks)
card = telegram_view.card_text(draft)
assert "Emosi terbalik" in card
keyboard = telegram_view.card_keyboard(draft, wp_ready=True)
datas = [b.callback_data for row in keyboard.inline_keyboard for b in row if b.callback_data]
assert all(len(d.encode()) <= 64 for d in datas) and "d:selftest:w" in datas
assert telegram_view.parse_cb("d:selftest:t:3") == {"draft": "selftest", "action": "t", "arg": "3"}
print("telegram view ok")

for text in (bot_app.HELP_TEXT, card, telegram_view.titles_text(draft)):
    visible = text.replace("/wp url", "")
    assert not humanizer.forbidden_chars(visible), humanizer.forbidden_chars(visible)
assert bot_app.fallback_intent("x" * 250, None)["intent"] == "compose"
app = bot_app.build_application()
print("bot handlers:", len(app.handlers[0]))
print("ALL SELFTEST PASSED")
