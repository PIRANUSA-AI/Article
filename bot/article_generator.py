import copy
import difflib
import json
import re

import config
import humanizer
import qwen_client
import transcript_source

TONES = [
    {
        "key": "edukatif",
        "label": "Edukatif",
        "brief": "Menjanjikan pemahaman atau keterampilan yang jelas. Pembaca langsung tahu apa yang bisa dia lakukan setelah membaca.",
    },
    {
        "key": "penasaran",
        "label": "Penasaran",
        "brief": "Membuka celah rasa ingin tahu tanpa menipu. Sebut hal tak terduga yang memang benar menurut bahan, tapi jangan bocorkan semuanya.",
    },
    {
        "key": "waspada",
        "label": "Waspada",
        "brief": "Menyorot risiko, kesalahan yang sering terjadi, atau kerugian yang bisa dihindari. Hati hati, bukan menakut nakuti.",
    },
    {
        "key": "kontras",
        "label": "Kontras",
        "brief": "Membandingkan dua hal: cara lama lawan cara baru, sebelum lawan sesudah, manual lawan otomatis, harapan lawan kenyataan.",
    },
    {
        "key": "terbalik",
        "label": "Emosi terbalik",
        "brief": "Membalik asumsi pembaca. Buka dari sisi negatif, kekesalan, atau anggapan yang kelihatannya benar padahal keliru, lalu arahkan ke jawaban positif. Boleh sedikit memancing debat, tetap jujur.",
    },
]
TONE_KEYS = [t["key"] for t in TONES]
TONE_LABELS = {t["key"]: t["label"] for t in TONES}
BLOCK_TYPES = ("paragraph", "list", "steps", "quote", "callout")

SOURCE_LABELS = {"video": "video", "image": "gambar", "text": "catatan"}
SUMMARY_HEADINGS = {"video": "Ringkasan video", "image": "Ringkasan", "text": "Ringkasan"}
LENGTHS = {"video": "800 sampai 1400 kata", "image": "450 sampai 900 kata", "text": "600 sampai 1200 kata"}


class ArticleError(RuntimeError):
    pass


def _system_prompt():
    return (
        "Kamu penulis konten senior untuk blog %s (%s). %s\n"
        "Tugasmu mengubah bahan mentah (transkrip video, pengamatan gambar, atau catatan) menjadi artikel blog berbahasa Indonesia "
        "yang enak dibaca, akurat, dan bikin orang betah sampai akhir.\n"
        "Suara penulisan: %s\n"
        "Balas hanya dengan satu objek JSON valid.\n\n"
        "Panduan gaya berikut wajib kamu jalankan dalam Mode tersemat, artinya langsung tulis versi final yang sudah bersih:\n"
        "<panduan_humanizer>\n%s\n</panduan_humanizer>"
    ) % (config.SITE_TITLE, config.SITE_LINK, config.BRAND_CONTEXT, config.ARTICLE_VOICE, humanizer.rules())


def _mmss(seconds):
    seconds = int(seconds or 0)
    return "%02d:%02d" % (seconds // 60, seconds % 60)


def condense_transcript(snippets):
    paragraphs = transcript_source.as_paragraphs(snippets)
    chunks = []
    current = []
    length = 0
    for para in paragraphs:
        if length + len(para["text"]) > config.QWEN_CHUNK_CHARS and current:
            chunks.append(current)
            current = []
            length = 0
        current.append(para)
        length += len(para["text"]) + 1
    if current:
        chunks.append(current)
    if len(chunks) <= 1:
        body = "\n\n".join("[%s] %s" % (_mmss(p["start"]), p["text"]) for p in (chunks[0] if chunks else []))
        return body
    notes = []
    for index, chunk in enumerate(chunks):
        body = "\n\n".join("[%s] %s" % (_mmss(p["start"]), p["text"]) for p in chunk)
        prompt = (
            "Ringkas potongan %d dari %d transkrip video berikut menjadi catatan terstruktur. "
            "Pertahankan semua nama, angka, istilah teknis, langkah, definisi, dan kalimat yang layak dikutip persis. "
            "Sertakan timestamp untuk poin kunci. Jangan menambah opini.\n\n" % (index + 1, len(chunks)) + body
        )
        note, _model = qwen_client.chat(
            [{"role": "system", "content": "Kamu peringkas transkrip yang setia pada sumber."}, {"role": "user", "content": prompt}],
            models=qwen_client.fast_models(),
            temperature=0.2,
            max_tokens=3000,
        )
        notes.append("CATATAN BAGIAN %d:\n%s" % (index + 1, note))
    return "\n\n".join(notes)


def material_for_video(video_info, transcript_text, language):
    description = (video_info.get("description") or "").strip()
    lines = [
        "SUMBER: video YouTube",
        "Judul asli video (jangan disalin jadi judul artikel): %s" % video_info.get("title"),
        "Channel: %s" % video_info.get("channel"),
        "Durasi: %s" % _mmss(video_info.get("duration")),
        "URL: %s" % video_info.get("url"),
        "Bahasa transkrip: %s" % language,
    ]
    if description:
        lines += ["", "DESKRIPSI VIDEO (bisa berisi promosi, pakai seperlunya):", description[:1500]]
    body = transcript_text
    if len(body) > config.QWEN_MAX_CHARS:
        body = body[: config.QWEN_MAX_CHARS] + "\n[transkrip terpotong]"
    lines += ["", "TRANSKRIP (timestamp hanya untuk orientasi, jangan ditulis di artikel):", body]
    return "\n".join(lines)


def material_for_images(entries, notes, caption):
    lines = ["SUMBER: gambar kiriman user"]
    if caption:
        lines += ["", "KETERANGAN DARI USER:", caption]
    for entry in entries:
        note = notes.get(entry["key"]) or {}
        lines.append("")
        lines.append("[%s] %s" % (entry["key"], note.get("description") or "(tidak terbaca)"))
        if note.get("on_screen_text"):
            lines.append("Teks terlihat: %s" % note["on_screen_text"])
        for fact in note.get("facts") or []:
            lines.append("Fakta: %s" % fact)
    return "\n".join(lines)


def material_for_text(text):
    return "SUMBER: catatan atau teks dari user\n\n" + text.strip()[: config.QWEN_MAX_CHARS]


def _image_menu(entries, notes):
    if not entries:
        return "(tidak ada)"
    rows = []
    for entry in entries:
        note = notes.get(entry["key"]) or {}
        rows.append(
            "[%s] %s%s. Teks: %s"
            % (
                entry["key"],
                ("menit %s, " % entry["label"]) if entry.get("label") and ":" in entry["label"] else "",
                note.get("description") or "",
                note.get("on_screen_text") or "tidak ada",
            )
        )
    return "\n".join(rows)


def _rules(kind, source_title, image_count, max_inline, has_brief):
    tones = "\n".join("   %s: %s" % (t["key"], t["brief"]) for t in TONES)
    if image_count:
        image_rule = (
            "Ada gambar pendukung di daftar GAMBAR TERSEDIA. Pakai paling banyak %d, taruh di bagian isi yang pembahasannya paling cocok "
            "dengan gambar itu dengan mengisi field image memakai kodenya. Satu gambar hanya boleh dipakai sekali. Bagian lain isi null. "
            "Lebih baik tidak memakai gambar daripada menaruhnya di bagian yang tidak nyambung." % max_inline
        )
    else:
        image_rule = "Tidak ada gambar pendukung. Isi semua field image dengan null."
    title_guard = (
        'Jangan menyalin, menerjemahkan mentah, atau sekadar mengubah sedikit judul asli sumber ("%s"). Pikirkan sudut pandang baru.' % source_title
        if source_title
        else "Pikirkan sudut pandang yang segar."
    )
    brief_rule = "Arahan user di bagian ARAHAN USER menang atas aturan gaya, kecuali aturan akurasi dan aturan karakter." if has_brief else ""
    return (
        "ATURAN ARTIKEL\n"
        "1. Artikel terdiri dari tujuh bagian: judul, subjudul, ringkasan, isi, kesimpulan, ajakan (CTA), glosarium (opsional).\n"
        "2. Judul: buat lima opsi, tepat satu untuk tiap nada berikut, urut sesuai daftar:\n%s\n"
        "   Tiap judul 40 sampai 70 karakter, memuat kata kunci utama, huruf kapital hanya di awal kalimat dan nama diri, tanpa tanda seru berderet, "
        "tanpa janji yang tidak ada di bahan. %s\n"
        "   Tiap judul punya subjudul sendiri: satu kalimat 80 sampai 160 karakter yang melanjutkan janji judulnya, bukan mengulanginya.\n"
        "   Isi recommended dengan nomor urut (0 sampai 4) judul yang paling kuat menarik pembaca blog ini.\n"
        "3. Ringkasan: satu paragraf 2 sampai 3 kalimat yang menjelaskan isi %s secara padat, lalu 3 sampai 5 poin kunci pendek. "
        "Pembaca yang hanya membaca bagian ini sudah dapat intinya.\n"
        "4. Isi: 3 sampai 6 bagian. Bentuknya bebas mengikuti bahan. Tutorial pakai langkah bernomor, ulasan fitur boleh membandingkan, cerita boleh mengalir. "
        "Jangan membuat semua bagian berbentuk sama. Judul bagian pendek dan spesifik, huruf kapital hanya di awal, tanpa nomor, bukan kalimat pembuka generik.\n"
        "   Jenis blok: paragraph (1 sampai 4 kalimat, panjang kalimat bervariasi), list (poin sejajar), steps (langkah berurutan), "
        "quote (kutipan persis dari bahan, isi by dengan nama pembicara kalau jelas, kalau tidak pakai nama channel atau kosongkan), "
        "callout (satu tips atau peringatan praktis). Tidak wajib memakai semua jenis. Tebal dengan **teks** boleh, paling banyak sekali per bagian.\n"
        "5. Gambar: %s\n"
        "6. Kesimpulan: judul bagiannya boleh Kesimpulan atau frasa lain yang lebih hidup. 1 sampai 2 paragraf yang menjawab apa artinya buat pembaca, "
        "jangan mengulang ringkasan dan jangan menutup dengan kalimat motivasi kosong.\n"
        "7. CTA: 1 sampai 2 kalimat yang mengajak pembaca menekan tombol WhatsApp tepat di bawah kalimat ini untuk konsultasi gratis dengan tim %s, dikaitkan dengan topik artikel. "
        "Tombolnya dipasang otomatis oleh sistem, jadi jangan menulis nomor telepon, link, atau teks tombolnya.\n"
        "8. Glosarium: hanya kalau bahan memuat istilah teknis yang mungkin asing bagi pembaca awam. Paling banyak 8 istilah, definisi satu kalimat. "
        "Jangan masukkan hal yang sudah umum diketahui seperti nama toko aplikasi, merek ponsel, atau kata sehari hari. "
        "Kalau tidak ada istilah teknis, isi array kosong.\n"
        "9. Akurasi: setiap angka, nama, fitur, harga, dan klaim harus ada di bahan, termasuk di judul dan subjudul. Konsep umum boleh dijelaskan, data jangan dikarang. "
        "Jangan menambah angka waktu atau jumlah, perangkat, edisi produk, atau skenario lapangan yang tidak disebut bahan. "
        "Ilustrasi boleh dipakai kalau jelas ditulis sebagai contoh, misalnya dengan kata misalnya.\n"
        "   Untuk bahan gambar, tulis isinya langsung. Jangan menulis frasa seperti dari tangkapan layar yang kami lihat.\n"
        "10. Jangan menulis timestamp di teks. Jangan mengulang ulang frasa seperti di video ini narasumber mengatakan. "
        "Tulis sebagai artikel yang berdiri sendiri dan sebut sumber seperlunya.\n"
        "11. Karakter terlarang di semua teks: em dash, en dash, tanda hubung, titik koma, emoji, kutip melengkung. Kata ulang ditulis dengan spasi. "
        "Pengecualian hanya untuk nama produk resmi, URL, dan slug.\n"
        "12. Panjang isi total %s.\n"
        "13. Metadata: excerpt 120 sampai 150 karakter untuk meta description dan wajib memuat focus_keyword, "
        "focus_keyword 2 sampai 4 kata yang muncul persis di semua opsi judul dan di paragraf ringkasan, "
        "slug pendek huruf kecil dipisah tanda hubung yang memuat kata kunci, category satu nama singkat, tags 3 sampai 6. "
        "seo_title 40 sampai 58 karakter yang DIAWALI focus_keyword, untuk judul di hasil pencarian.\n"
        "14. SEO on page: focus_keyword wajib muncul di tiap subjudul opsi judul (karena subjudul jadi paragraf pertama), "
        "di paling tidak satu judul bagian isi, dan tersebar 3 sampai 6 kali di isi secara wajar. Jangan dijejalkan.\n"
        "15. Link: sisipkan 2 sampai 3 link internal dari daftar LINK INTERNAL dan 1 link keluar dari daftar LINK LUAR "
        "di dalam paragraf yang relevan, dengan format [teks jangkar](url). Teks jangkar 2 sampai 6 kata yang menjelaskan tujuan link, "
        "jangan memakai focus_keyword persis sebagai teks jangkar. Jangan membuat URL di luar kedua daftar itu. Kalau daftar kosong, lewati.\n"
        "%s"
    ) % (
        tones,
        title_guard,
        SOURCE_LABELS.get(kind, "bahan"),
        image_rule,
        config.SITE_TITLE,
        LENGTHS.get(kind, LENGTHS["text"]),
        brief_rule,
    )


SCHEMA = (
    '{"title_options": [{"tone": "edukatif", "title": "...", "subtitle": "..."}, {"tone": "penasaran", ...}, {"tone": "waspada", ...}, '
    '{"tone": "kontras", ...}, {"tone": "terbalik", ...}], "recommended": 0, '
    '"summary": {"text": "...", "points": ["..."]}, '
    '"sections": [{"heading": "...", "image": "kode gambar atau null", "blocks": [{"type": "paragraph", "text": "..."}, '
    '{"type": "steps", "items": ["..."]}, {"type": "list", "items": ["..."]}, {"type": "quote", "text": "...", "by": "..."}, '
    '{"type": "callout", "text": "..."}]}], '
    '"conclusion": {"heading": "...", "paragraphs": ["..."]}, "cta": "...", '
    '"glossary": [{"term": "...", "definition": "..."}], '
    '"excerpt": "...", "seo_title": "...", "focus_keyword": "...", "slug": "...", "category": "...", "tags": ["..."]}'
)

LINK_RE = re.compile(r"\[([^\]\n]{1,120})\]\((https?://[^)\s]+)\)")


def _link_menu(links):
    links = links or {}
    internal = "\n".join("%s | %s" % (p["title"], p["url"]) for p in links.get("internal") or []) or "(kosong)"
    external = "\n".join(links.get("external") or []) or "(kosong)"
    return "LINK INTERNAL (judul | url):\n%s\n\nLINK LUAR:\n%s" % (internal, external)


def _allowed_urls(links):
    links = links or {}
    return {p["url"] for p in links.get("internal") or []} | set(links.get("external") or [])


def enforce_links(article):
    allowed = _allowed_urls(article.get("_links"))

    def fix(text):
        return LINK_RE.sub(lambda m: m.group(0) if m.group(2) in allowed else m.group(1), text or "")

    for path, text in _prose_fields(article):
        if "[" in (text or ""):
            _set(article, path, fix(text))
    internal = [p for p in (article.get("_links") or {}).get("internal") or []]
    if internal and not count_links(article)["internal"]:
        target = internal[0]
        article["sections"][-1]["blocks"].append({"type": "paragraph", "text": "Baca juga: [%s](%s)." % (target["title"], target["url"])})
    return article


def count_links(article):
    internal_urls = {p["url"] for p in (article.get("_links") or {}).get("internal") or []}
    counts = {"internal": 0, "external": 0}
    for _path, text in _prose_fields(article):
        for match in LINK_RE.finditer(text or ""):
            counts["internal" if match.group(2) in internal_urls else "external"] += 1
    return counts


def _stem(word):
    return re.sub(r"(nya|lah|kah)$", "", word)


def has_words(text, keyword):
    words = {_stem(w) for w in _normalized(keyword)}
    if not words:
        return False
    for sentence in re.split(r"(?<=[.!?])\s+", LINK_RE.sub(r"\1", text or "")):
        if words <= {_stem(w) for w in _normalized(sentence)}:
            return True
    return False


def _keyword_count(article):
    if not _normalized(article.get("focus_keyword")):
        return 0
    body = []
    for section in article["sections"]:
        for block in section["blocks"]:
            body += block.get("items") or [block.get("text", "")]
    body += [article["summary"]["text"]] + article["conclusion"]["paragraphs"]
    count = 0
    for text in body:
        for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
            if has_words(sentence, article["focus_keyword"]):
                count += 1
    return count


def seo_report(article, slug=""):
    keyword = article.get("focus_keyword") or ""
    links = count_links(article)
    return {
        "keyword": keyword,
        "in_title": has_keyword(article.get("title"), keyword),
        "in_intro": has_words(article.get("subtitle"), keyword),
        "in_heading": any(has_words(s["heading"], keyword) for s in article["sections"]),
        "in_meta": has_keyword(article.get("excerpt"), keyword),
        "in_slug": has_keyword((slug or article.get("slug") or "").replace("-", " "), keyword),
        "seo_title_start": " ".join(_normalized(article.get("seo_title"))).startswith(" ".join(_normalized(keyword))) if keyword else False,
        "count": _keyword_count(article),
        "internal": links["internal"],
        "external": links["external"],
        "meta_length": len(article.get("excerpt") or ""),
    }


def _starts_with(text, keyword):
    return bool(keyword) and " ".join(_normalized(text)).startswith(" ".join(_normalized(keyword)))


def _fix_seo_title(article):
    keyword = article.get("focus_keyword") or ""
    title = humanizer.sanitize_title(article.get("seo_title"), article.get("_keep") or ())
    if keyword and not _starts_with(title, keyword):
        rest = article.get("title") or ""
        if _starts_with(rest, keyword):
            title = rest
        else:
            tail = re.sub(re.escape(keyword), "", rest, flags=re.IGNORECASE).strip(" :,")
            title = "%s: %s" % (keyword, tail[:1].lower() + tail[1:]) if tail else keyword
    if len(title) > 60:
        title = title[:60].rsplit(" ", 1)[0].rstrip(",:")
    article["seo_title"] = title
    return article


def seo_pass(article):
    keyword = article.get("focus_keyword")
    if not keyword:
        return article
    report = seo_report(article)
    links = article.get("_links") or {}
    need = []
    if not report["in_intro"]:
        need.append("subtitle belum memuat semua kata dari kata kunci dalam satu kalimat")
    if not report["in_heading"]:
        need.append("belum ada judul bagian isi yang memuat kata kunci")
    if report["count"] < 3:
        need.append("kata kunci baru muncul %d kali di isi, targetnya 3 sampai 5 kalimat" % report["count"])
    if report["internal"] < 2 and links.get("internal"):
        need.append("link internal baru %d, targetnya 2" % report["internal"])
    if report["external"] < 1 and links.get("external"):
        need.append("belum ada link keluar, targetnya 1")
    if not report["seo_title_start"]:
        need.append("seo_title harus diawali kata kunci persis, 40 sampai 58 karakter")
    if not need:
        return article
    paragraphs = {}
    for s, section in enumerate(article["sections"]):
        for b, block in enumerate(section["blocks"]):
            if block["type"] in ("paragraph", "callout"):
                paragraphs["s%db%d" % (s, b)] = block["text"]
    payload = {
        "kata_kunci": keyword,
        "judul": article["title"],
        "subtitle": article.get("subtitle"),
        "subtitle_opsi": {o["tone"]: o.get("subtitle") for o in article.get("title_options") or []},
        "judul_bagian": {str(i): s["heading"] for i, s in enumerate(article["sections"])},
        "paragraf": paragraphs,
        "seo_title": article.get("seo_title"),
    }
    prompt = (
        "Perbaiki SEO artikel ini dengan perubahan sekecil mungkin. Yang masih kurang:\n- "
        + "\n- ".join(need)
        + "\n\nAturan: kata kunci boleh ditulis dengan urutan kata yang wajar asal semua katanya ada dalam satu kalimat. "
        "Tulisan harus tetap alami, jangan dijejalkan, jangan menambah fakta baru. "
        "Link ditulis [teks jangkar](url), teks jangkar 2 sampai 6 kata yang menjelaskan tujuan link, bukan kata kunci persis, "
        "dan hanya boleh memakai URL dari daftar berikut. Link yang sudah ada jangan dihapus.\n"
        + _link_menu(links)
        + "\n\nData artikel:\n"
        + json.dumps(payload, ensure_ascii=False)
        + '\n\nBalas JSON hanya berisi bagian yang berubah: {"subtitle": "...", "subtitle_opsi": {"tone": "..."}, '
        '"judul_bagian": {"indeks": "..."}, "paragraf": {"id": "..."}, "seo_title": "..."}'
    )
    try:
        data, _model = qwen_client.chat_json(_system_prompt(), prompt, models=qwen_client.text_models(), temperature=0.4, max_tokens=5000)
    except Exception:
        return article
    if _clean(data.get("subtitle")):
        article["subtitle"] = _clean(data["subtitle"])
    for option in article.get("title_options") or []:
        new = _clean((data.get("subtitle_opsi") or {}).get(option["tone"]))
        if new:
            option["subtitle"] = new
    active = next((o for o in article.get("title_options") or [] if o["title"] == article["title"]), None)
    if active and _clean(data.get("subtitle")):
        active["subtitle"] = article["subtitle"]
    for index, heading in (data.get("judul_bagian") or {}).items():
        try:
            position = int(index)
        except (TypeError, ValueError):
            continue
        if 0 <= position < len(article["sections"]) and _clean(heading):
            article["sections"][position]["heading"] = _clean(heading)
    for key, text in (data.get("paragraf") or {}).items():
        match = re.fullmatch(r"s(\d+)b(\d+)", str(key))
        if not match or not _clean(text):
            continue
        s, b = int(match.group(1)), int(match.group(2))
        if s < len(article["sections"]) and b < len(article["sections"][s]["blocks"]):
            block = article["sections"][s]["blocks"][b]
            if block["type"] in ("paragraph", "callout"):
                block["text"] = _clean(text)
    if _clean(data.get("seo_title")):
        article["seo_title"] = _clean(data["seo_title"])
    for path, text in _prose_fields(article):
        if path[-1] == "heading":
            _set(article, path, humanizer.sanitize_title(text, article.get("_keep") or ()))
        elif not _is_quote(article, path):
            _set(article, path, humanizer.sanitize(text))
    for option in article.get("title_options") or []:
        option["subtitle"] = humanizer.sanitize(option.get("subtitle"))
    enforce_links(article)
    _fix_seo_title(article)
    return article


def write(kind, material, source_title="", image_entries=None, image_notes=None, brief=None, max_inline=None, links=None):
    image_entries = image_entries or []
    image_notes = image_notes or {}
    max_inline = config.MAX_INLINE_IMAGES if max_inline is None else max_inline
    prompt = "\n".join(
        [
            material,
            "",
            "GAMBAR TERSEDIA:",
            _image_menu(image_entries, image_notes),
            "",
            _link_menu(links),
            "",
            "ARAHAN USER:",
            brief or "(tidak ada)",
            "",
            _rules(kind, source_title, len(image_entries), max_inline, bool(brief)),
            "",
            "Balas JSON dengan skema:",
            SCHEMA,
        ]
    )
    allowed = [e["key"] for e in image_entries]
    article = None
    data = {}
    model = ""
    problems = []
    for thinking in (config.QWEN_WRITE_THINKING or False, False):
        data, model = qwen_client.chat_json(
            _system_prompt(),
            prompt,
            models=qwen_client.text_models(),
            temperature=0.7,
            max_tokens=10000,
            thinking=thinking,
        )
        try:
            candidate = normalize(data, kind, allowed, max_inline)
        except ArticleError as exc:
            problems = [str(exc)]
            continue
        problems = _missing_parts(candidate)
        if article is None or len(problems) < len(_missing_parts(article)):
            article = candidate
            chosen = (data, model)
        if not problems:
            break
    if article is None:
        raise ArticleError("artikel gagal disusun: %s" % "; ".join(problems))
    data, model = chosen
    _fill_meta(article)
    article["_keep"] = sorted(keep_words(article, material))
    article["title_options"] = _filter_titles(article["title_options"], source_title, article["_keep"])
    if len(article["title_options"]) < 3:
        try:
            extra = retitle(article, material, source_title, [o["title"] for o in article["title_options"]])
        except Exception:
            extra = []
        article["title_options"] = _merge_options(article["title_options"], extra)
    if not article["title_options"]:
        raise ArticleError("model tidak menghasilkan judul yang berbeda dari judul sumber")
    choice = _prefer_keyword(article["title_options"], article.get("focus_keyword"), _recommended_index(data, article["title_options"]))
    apply_title(article, choice)
    article["_model"] = model
    article["_links"] = links or {}
    return seo_pass(polish(article))


def _missing_parts(article):
    missing = []
    if len(article["sections"]) < 3:
        missing.append("bagian isi kurang dari 3")
    if not article["conclusion"]["paragraphs"]:
        missing.append("kesimpulan kosong")
    if not article.get("cta"):
        missing.append("CTA kosong")
    if len(article.get("title_options") or []) < 4:
        missing.append("opsi judul kurang")
    if not article["summary"]["text"]:
        missing.append("ringkasan kosong")
    return missing


def _fill_meta(article):
    if article.get("excerpt") and article.get("focus_keyword") and article.get("slug") and len(article.get("tags") or []) >= 2:
        return
    outline = {
        "judul": [o["title"] for o in article.get("title_options") or []][:2],
        "ringkasan": article["summary"]["text"],
        "bagian": [s["heading"] for s in article["sections"]],
    }
    prompt = (
        "Buat metadata SEO untuk artikel blog ini.\n"
        + json.dumps(outline, ensure_ascii=False)
        + '\nBalas JSON: {"excerpt": "120 sampai 155 karakter, tanpa tanda hubung", "focus_keyword": "2 sampai 4 kata", '
        '"slug": "huruf kecil dipisah tanda hubung", "category": "satu nama singkat", "tags": ["3 sampai 6 tag"]}'
    )
    try:
        data, _model = qwen_client.chat_json("Kamu editor SEO blog berbahasa Indonesia.", prompt, models=qwen_client.fast_models(), max_tokens=600)
    except Exception:
        data = {}
    if not article.get("excerpt"):
        article["excerpt"] = _clean(data.get("excerpt"))[:160] or article["summary"]["text"][:155]
    if not article.get("focus_keyword"):
        article["focus_keyword"] = _clean(data.get("focus_keyword"))[:60]
    if not article.get("slug"):
        article["slug"] = re.sub(r"[^a-z0-9]+", "-", _clean(data.get("slug")).lower()).strip("-")[:70]
    if len(article.get("tags") or []) < 2 or article["tags"] == [config.WP_DEFAULT_TAG]:
        tags = list(dict.fromkeys(_clean_items(data.get("tags"))))[:6]
        if tags:
            article["tags"] = tags
    if article.get("category") == config.WP_DEFAULT_CATEGORY and _clean(data.get("category")):
        article["category"] = _clean(data.get("category"))


def has_keyword(text, keyword):
    words = _normalized(keyword)
    return bool(words) and " ".join(words) in " ".join(_normalized(text))


def _prefer_keyword(options, keyword, index):
    if not keyword or not options or has_keyword(options[index]["title"], keyword):
        return index
    for position, option in enumerate(options):
        if has_keyword(option["title"], keyword):
            return position
    return index


def trim_meta(text, limit=155):
    text = _clean(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "."


def _recommended_index(data, options):
    try:
        wanted = int(data.get("recommended"))
    except (TypeError, ValueError):
        wanted = 0
    raw = data.get("title_options") or []
    if 0 <= wanted < len(raw) and isinstance(raw[wanted], dict):
        tone = _clean(raw[wanted].get("tone")).lower() or (TONE_KEYS[wanted] if wanted < len(TONE_KEYS) else "")
        for index, option in enumerate(options):
            if option["tone"] == tone:
                return index
    return 0


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_items(items):
    return [_clean(i) for i in (items or []) if _clean(i)]


def normalize(data, kind, allowed_images, max_inline):
    if not isinstance(data, dict):
        raise ArticleError("output artikel bukan objek JSON")
    article = {"kind": kind}
    options = []
    for index, item in enumerate(data.get("title_options") or []):
        if not isinstance(item, dict):
            continue
        tone = _clean(item.get("tone")).lower()
        if tone not in TONE_KEYS:
            tone = TONE_KEYS[index] if index < len(TONE_KEYS) else "edukatif"
        title = _clean(item.get("title"))
        if title:
            options.append({"tone": tone, "title": title, "subtitle": _clean(item.get("subtitle"))})
    if not options and data.get("title"):
        options.append({"tone": "edukatif", "title": _clean(data.get("title")), "subtitle": _clean(data.get("subtitle"))})
    article["title_options"] = options

    summary = data.get("summary") or {}
    if isinstance(summary, str):
        summary = {"text": summary, "points": []}
    article["summary"] = {"text": _clean(summary.get("text")), "points": _clean_items(summary.get("points"))[:5]}

    sections = []
    used_images = set()
    for item in data.get("sections") or []:
        if not isinstance(item, dict):
            continue
        blocks = []
        for block in item.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            kind_name = _clean(block.get("type")).lower()
            if kind_name not in BLOCK_TYPES:
                kind_name = "paragraph"
            if kind_name in ("list", "steps"):
                items = _clean_items(block.get("items"))
                if items:
                    blocks.append({"type": kind_name, "items": items})
            elif kind_name == "quote":
                text = _clean(block.get("text")).strip("\"'")
                if text:
                    blocks.append({"type": "quote", "text": text, "by": _clean(block.get("by"))})
            else:
                text = _clean(block.get("text"))
                if text:
                    blocks.append({"type": kind_name, "text": text})
        for legacy in _clean_items(item.get("paragraphs")):
            blocks.append({"type": "paragraph", "text": legacy})
        image = _clean(item.get("image")).strip("[]").upper()
        if image not in allowed_images or image in used_images or len(used_images) >= max_inline:
            image = None
        if image:
            used_images.add(image)
        heading = _clean(item.get("heading"))
        if blocks or heading:
            sections.append({"heading": heading, "image": image, "blocks": blocks})
    if not sections:
        raise ArticleError("artikel tidak punya isi")
    article["sections"] = sections

    conclusion = data.get("conclusion") or {}
    if isinstance(conclusion, str):
        conclusion = {"heading": "Kesimpulan", "paragraphs": [conclusion]}
    article["conclusion"] = {
        "heading": _clean(conclusion.get("heading")) or "Kesimpulan",
        "paragraphs": _clean_items(conclusion.get("paragraphs")),
    }
    cta = data.get("cta")
    if isinstance(cta, dict):
        cta = cta.get("text")
    article["cta"] = _clean(cta)
    glossary = []
    for item in data.get("glossary") or []:
        if isinstance(item, dict) and _clean(item.get("term")) and _clean(item.get("definition")):
            glossary.append({"term": _clean(item.get("term")), "definition": _clean(item.get("definition"))})
    article["glossary"] = glossary[:8]
    article["excerpt"] = _clean(data.get("excerpt"))[:160]
    article["focus_keyword"] = _clean(data.get("focus_keyword"))[:60]
    article["seo_title"] = _clean(data.get("seo_title"))[:90]
    article["slug"] = re.sub(r"[^a-z0-9]+", "-", _clean(data.get("slug")).lower()).strip("-")[:70]
    article["category"] = _clean(data.get("category")) or config.WP_DEFAULT_CATEGORY
    tags = list(dict.fromkeys(_clean_items(data.get("tags"))))[:6]
    article["tags"] = tags or [config.WP_DEFAULT_TAG]
    article["title"] = _clean(data.get("title"))
    article["subtitle"] = _clean(data.get("subtitle"))
    article["tone"] = _clean(data.get("tone"))
    return article


def _normalized(text):
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split()


def too_similar(candidate, source_title):
    if not source_title:
        return False
    a, b = _normalized(candidate), _normalized(source_title)
    if not a or not b:
        return False
    ratio = difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    overlap = len(set(a) & set(b)) / float(len(set(a) | set(b)))
    return ratio >= 0.72 or overlap >= 0.7


def keep_words(article, material=""):
    body = [article["summary"]["text"]] + article["summary"]["points"]
    for section in article["sections"]:
        for block in section["blocks"]:
            body += block.get("items") or [block.get("text", "")]
    return humanizer.proper_words(" ".join(body) + "\n" + (material or ""))


def _filter_titles(options, source_title, keep=()):
    kept = []
    seen = set()
    for option in options:
        option = dict(option)
        option["title"] = humanizer.sanitize_title(option["title"], keep)
        option["subtitle"] = humanizer.sanitize(option.get("subtitle"))
        key = option["title"].lower()
        if not option["title"] or key in seen or too_similar(option["title"], source_title):
            continue
        seen.add(key)
        kept.append(option)
    return kept


def _merge_options(current, extra):
    by_tone = {o["tone"]: o for o in current}
    for option in extra:
        by_tone.setdefault(option["tone"], option)
    return [by_tone[k] for k in TONE_KEYS if k in by_tone]


def apply_title(article, index):
    options = article.get("title_options") or []
    if not options:
        article["title"] = article.get("title") or "Artikel baru"
        return article
    index = max(0, min(int(index), len(options) - 1))
    chosen = options[index]
    article["title"] = chosen["title"]
    article["subtitle"] = chosen.get("subtitle") or article.get("subtitle") or ""
    article["tone"] = chosen["tone"]
    return article


def retitle(article, material, source_title, avoid):
    outline = "\n".join("- %s" % s["heading"] for s in article.get("sections") or [])
    prompt = "\n".join(
        [
            "Ringkasan artikel: %s" % (article.get("summary") or {}).get("text", ""),
            "Bagian isi:",
            outline,
            "Kata kunci utama: %s" % article.get("focus_keyword", ""),
            "",
            "Potongan bahan:",
            (material or "")[:6000],
            "",
            "Judul yang sudah ada dan tidak boleh dipakai lagi:",
            "\n".join("- %s" % t for t in avoid) or "(tidak ada)",
            "",
            "Buat lima judul baru beserta subjudulnya, tepat satu untuk tiap nada:",
            "\n".join("%s: %s" % (t["key"], t["brief"]) for t in TONES),
            "Tiap judul 40 sampai 70 karakter, memuat kata kunci utama, tidak menyalin judul asli sumber (\"%s\"), tidak menjanjikan hal yang tidak ada di bahan. "
            "Huruf kapital hanya di awal judul dan pada nama diri atau merek. "
            "Subjudul satu kalimat 80 sampai 160 karakter. Tanpa em dash, en dash, tanda hubung, titik koma, dan emoji."
            % (source_title or "tidak ada"),
            'Balas JSON: {"title_options": [{"tone": "...", "title": "...", "subtitle": "..."}], "recommended": 0}',
        ]
    )
    data, _model = qwen_client.chat_json(_system_prompt(), prompt, models=qwen_client.text_models(), temperature=0.9, max_tokens=2000)
    options = []
    for index, item in enumerate(data.get("title_options") or []):
        if not isinstance(item, dict) or not _clean(item.get("title")):
            continue
        tone = _clean(item.get("tone")).lower()
        if tone not in TONE_KEYS:
            tone = TONE_KEYS[index % len(TONE_KEYS)]
        options.append({"tone": tone, "title": _clean(item.get("title")), "subtitle": _clean(item.get("subtitle"))})
    avoid_keys = {a.lower() for a in avoid}
    keep = article.get("_keep") or sorted(keep_words(article, material))
    return [o for o in _filter_titles(options, source_title, keep) if o["title"].lower() not in avoid_keys]


def _prose_fields(article):
    fields = [(("subtitle",), article.get("subtitle", ""))]
    fields.append((("summary", "text"), article["summary"]["text"]))
    for i, point in enumerate(article["summary"]["points"]):
        fields.append((("summary", "points", i), point))
    for s, section in enumerate(article["sections"]):
        fields.append((("sections", s, "heading"), section["heading"]))
        for b, block in enumerate(section["blocks"]):
            if "items" in block:
                for i, item in enumerate(block["items"]):
                    fields.append((("sections", s, "blocks", b, "items", i), item))
            else:
                fields.append((("sections", s, "blocks", b, "text"), block["text"]))
    fields.append((("conclusion", "heading"), article["conclusion"]["heading"]))
    for i, para in enumerate(article["conclusion"]["paragraphs"]):
        fields.append((("conclusion", "paragraphs", i), para))
    fields.append((("cta",), article.get("cta", "")))
    for i, item in enumerate(article["glossary"]):
        fields.append((("glossary", i, "definition"), item["definition"]))
    fields.append((("excerpt",), article.get("excerpt", "")))
    return fields


def _set(article, path, value):
    target = article
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _is_quote(article, path):
    if len(path) >= 4 and path[0] == "sections" and path[2] == "blocks":
        return article["sections"][path[1]]["blocks"][path[3]]["type"] == "quote"
    return False


def polish(article):
    fields = _prose_fields(article)
    flagged = []
    total = 0
    for path, text in fields:
        if _is_quote(article, path):
            continue
        hits = humanizer.ai_smell(text)
        total += len(hits)
        if hits:
            flagged.append((path, text, hits))
    if flagged:
        payload = [{"id": i, "text": text, "pola": hits} for i, (path, text, hits) in enumerate(flagged)]
        prompt = (
            "Tulis ulang setiap teks di bawah supaya pola yang disebut di field pola hilang dan teksnya terbaca seperti ditulis manusia. "
            "Pertahankan semua fakta, angka, nama, dan maksudnya. Jangan menambah klaim baru. Panjang kurang lebih sama. "
            "Link berformat [teks](url) wajib dipertahankan persis, termasuk URLnya. "
            "Tanpa em dash, en dash, tanda hubung, titik koma, dan emoji.\n\n"
            + json.dumps(payload, ensure_ascii=False)
            + '\n\nBalas JSON: {"items": [{"id": 0, "text": "..."}]}'
        )
        try:
            data, _model = qwen_client.chat_json(_system_prompt(), prompt, models=qwen_client.fast_models(), temperature=0.5, max_tokens=6000)
            for item in data.get("items") or []:
                try:
                    index = int(item.get("id"))
                except (TypeError, ValueError):
                    continue
                text = _clean(item.get("text"))
                if 0 <= index < len(flagged) and text:
                    _set(article, flagged[index][0], text)
        except Exception:
            pass
    for path, _text in _prose_fields(article):
        current = article
        for key in path:
            current = current[key]
        if _is_quote(article, path):
            _set(article, path, humanizer.sanitize(current).replace(";", ","))
        elif path[-1] == "heading":
            _set(article, path, humanizer.sanitize_title(current, article.get("_keep") or ()))
        else:
            _set(article, path, humanizer.sanitize(current))
    article["title"] = humanizer.sanitize_title(article.get("title"), article.get("_keep") or ())
    for section in article["sections"]:
        for block in section["blocks"]:
            if block["type"] == "quote":
                block["by"] = humanizer.sanitize(block.get("by"))
    article["glossary"] = [
        {"term": _clean(g["term"]).replace(";", ","), "definition": g["definition"]} for g in article["glossary"] if g["definition"]
    ]
    article["tags"] = [humanizer.sanitize(t) or t for t in article["tags"]]
    article["category"] = humanizer.sanitize(article["category"]) or config.WP_DEFAULT_CATEGORY
    article["summary"]["points"] = [p for p in article["summary"]["points"] if p]
    article["excerpt"] = trim_meta(article.get("excerpt") or article["summary"]["text"])
    enforce_links(article)
    _fix_seo_title(article)
    article["_smell"] = total
    return article


EDITABLE_KEYS = ("title", "subtitle", "summary", "sections", "conclusion", "cta", "glossary", "excerpt", "seo_title", "focus_keyword", "category", "tags")


def revise(article, instruction, material, image_entries=None, image_notes=None, new_image=None):
    image_entries = image_entries or []
    image_notes = image_notes or {}
    current = {k: copy.deepcopy(article.get(k)) for k in EDITABLE_KEYS}
    allowed = [e["key"] for e in image_entries]
    limit = config.MAX_INLINE_IMAGES + (1 if new_image else 0)
    extra = ""
    if new_image:
        extra = (
            "\nUser menambahkan gambar baru dengan kode [%s]. Taruh di bagian yang paling cocok dengan mengisi field image bagian itu. "
            "Kalau bagian itu sudah punya gambar, ganti gambar lamanya hanya kalau user memintanya. Kalau perlu, tambahkan satu kalimat yang merujuk isi gambar.\n"
            % new_image
        )
    numbering = "\n".join("Bagian %d = %s" % (i + 1, s["heading"]) for i, s in enumerate(article["sections"]))
    prompt = "\n".join(
        [
            "ARTIKEL SAAT INI (JSON):",
            json.dumps(current, ensure_ascii=False),
            "",
            "NOMOR BAGIAN YANG DILIHAT USER (urutan array sections, ringkasan dan kesimpulan tidak dihitung):",
            numbering,
            "",
            "GAMBAR YANG BOLEH DIPAKAI:",
            _image_menu(image_entries, image_notes),
            "",
            "LINK YANG BOLEH DIPAKAI (format [teks](url), link lama pertahankan kecuali diminta):",
            _link_menu(article.get("_links")),
            "",
            "BAHAN ASLI (untuk menambah fakta kalau diminta):",
            (material or "")[:30000],
            "",
            "PERMINTAAN REVISI DARI USER:",
            instruction,
            extra,
            "Terapkan permintaan itu. Ubah hanya bagian yang diminta, bagian lain biarkan persis sama. "
            "Jangan menghapus, menggabungkan, atau mengurutkan ulang bagian yang tidak disebut user. "
            "Judul, subjudul, dan judul bagian memakai huruf kapital hanya di awal kalimat dan nama diri. "
            "Kalau permintaannya soal gaya atau panjang, terapkan ke bagian yang relevan saja. "
            "Kalau user minta judul baru, isi title dan subtitle baru. Semua aturan akurasi dan aturan karakter tetap berlaku. "
            "Paling banyak %d gambar di isi, tiap kode sekali." % limit,
            "",
            'Balas JSON: {"article": {objek dengan kunci yang sama seperti ARTIKEL SAAT INI}, "note": "satu kalimat bahasa Indonesia tentang apa yang kamu ubah"}',
        ]
    )
    allowed_removals = _requested_removals(instruction)
    for attempt in range(2):
        data, model = qwen_client.chat_json(_system_prompt(), prompt, models=qwen_client.text_models(), temperature=0.4, max_tokens=12000)
        updated = data.get("article") if isinstance(data.get("article"), dict) else data
        new_sections = updated.get("sections") if isinstance(updated.get("sections"), list) else current["sections"]
        removed = len(current["sections"]) - len(new_sections)
        if removed <= allowed_removals:
            break
        prompt += (
            "\n\nPERINGATAN: jawabanmu sebelumnya menghapus %d bagian padahal user hanya meminta %d. "
            "Ulangi dan pertahankan semua bagian lain." % (removed, allowed_removals)
        )
    else:
        updated = dict(updated, sections=current["sections"])
    merged = dict(current)
    for key in EDITABLE_KEYS:
        if key in updated and updated[key] not in (None, ""):
            merged[key] = updated[key]
    normalized = normalize(merged, article.get("kind", "text"), allowed, limit)
    result = dict(article)
    for key in EDITABLE_KEYS:
        result[key] = normalized[key]
    result["title"] = humanizer.sanitize_title(normalized["title"] or article.get("title"), article.get("_keep") or ())
    result["subtitle"] = normalized["subtitle"] or article.get("subtitle", "")
    if not result.get("slug"):
        result["slug"] = normalized.get("slug") or ""
    result["_model"] = model
    seo_pass(polish(result))
    note = humanizer.sanitize(data.get("note")) or "Revisi diterapkan."
    return result, note


def _requested_removals(instruction):
    lowered = (instruction or "").lower()
    if not re.search(r"\b(hapus|buang|hilangkan|gabung|gabungkan|singkirkan|potong|ringkas jadi)\w*", lowered):
        return 0
    numbers = set()
    for group in re.findall(r"bagian\s*((?:ke\s*)?\d+(?:\s*(?:,|dan|&)\s*\d+)*)", lowered):
        numbers |= set(re.findall(r"\d+", group))
    if re.search(r"\bsemua bagian\b", lowered):
        return 99
    return max(1, len(numbers))


def inline_images(article):
    return [s["image"] for s in article["sections"] if s.get("image")]


def word_count(article):
    parts = [article.get("title", ""), article.get("subtitle", ""), article["summary"]["text"]] + article["summary"]["points"]
    for section in article["sections"]:
        parts.append(section["heading"])
        for block in section["blocks"]:
            parts += block.get("items") or [block.get("text", "")]
    parts += article["conclusion"]["paragraphs"] + [article.get("cta", "")]
    parts += ["%s %s" % (g["term"], g["definition"]) for g in article["glossary"]]
    return len(re.findall(r"\w+", " ".join(parts)))


def to_markdown(article, source_url=None, summary_heading="Ringkasan"):
    lines = ["# %s" % article["title"], ""]
    if article.get("subtitle"):
        lines += ["_%s_" % article["subtitle"], ""]
    lines += ["## %s" % summary_heading, "", article["summary"]["text"], ""]
    lines += ["* %s" % p for p in article["summary"]["points"]]
    lines.append("")
    for section in article["sections"]:
        lines += ["## %s" % section["heading"], ""]
        if section.get("image"):
            lines += ["![%s](%s)" % (section["image"], section["image"]), ""]
        for block in section["blocks"]:
            if block["type"] == "list":
                lines += ["* %s" % i for i in block["items"]] + [""]
            elif block["type"] == "steps":
                lines += ["%d. %s" % (n + 1, i) for n, i in enumerate(block["items"])] + [""]
            elif block["type"] == "quote":
                lines += ["> %s" % block["text"]]
                if block.get("by"):
                    lines += [">", "> %s" % block["by"]]
                lines.append("")
            elif block["type"] == "callout":
                lines += ["> **Catatan:** %s" % block["text"], ""]
            else:
                lines += [block["text"], ""]
    lines += ["## %s" % article["conclusion"]["heading"], ""]
    for para in article["conclusion"]["paragraphs"]:
        lines += [para, ""]
    if article.get("cta"):
        lines += ["**%s**" % article["cta"], ""]
    if article["glossary"]:
        lines += ["## Glosarium", ""]
        lines += ["* **%s**: %s" % (g["term"], g["definition"]) for g in article["glossary"]]
        lines.append("")
    if source_url:
        lines += ["Sumber: %s" % source_url]
    return "\n".join(lines)
