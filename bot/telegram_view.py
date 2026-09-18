import html
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import article_generator
import pipeline
import wxr_builder

STATUS_LABELS = {
    "draft": "Draf",
    "publish": "Tayang",
    "pending": "Menunggu review",
    "private": "Privat",
    "future": "Terjadwal",
}
LIMIT = 3800


def esc(text):
    return html.escape(str(text or ""), quote=False)


def rich(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text))
    return re.sub(r"\[([^\]\n]{1,120})\]\((https?://[^)\s]+)\)", lambda m: '<a href="%s">%s</a>' % (html.escape(html.unescape(m.group(2))), m.group(1)), text)


def cb(draft_id, action, arg=None):
    value = "d:%s:%s" % (draft_id, action)
    if arg is not None:
        value += ":%s" % arg
    return value[:64]


def parse_cb(data):
    parts = (data or "").split(":")
    if len(parts) < 3 or parts[0] != "d":
        return None
    return {"draft": parts[1], "action": parts[2], "arg": parts[3] if len(parts) > 3 else None}


def _duration(seconds):
    seconds = int(seconds or 0)
    return "%d:%02d" % (seconds // 60, seconds % 60)


def source_line(draft):
    source = draft.get("source") or {}
    if draft["kind"] == "video":
        return 'video "%s" (%s, %s)' % (esc((source.get("title") or "").strip()), esc((source.get("channel") or "").strip()), _duration(source.get("duration")))
    users = sum(1 for img in draft["images"] if img.get("origin") == "user")
    if draft["kind"] == "image":
        return "%d foto kiriman kamu" % users
    return "catatan teks" + (" dan %d foto" % users if users else "")


def card_text(draft, headline="Draf siap"):
    article = draft["article"]
    info = pipeline.stats(draft)
    wp = draft.get("wp") or {}
    lines = ["<b>%s</b>" % esc(headline), "", "<b>%s</b>" % esc(article["title"])]
    if article.get("subtitle"):
        lines.append("<i>%s</i>" % esc(article["subtitle"]))
    lines.append("")
    tone = article_generator.TONE_LABELS.get(article.get("tone"), article.get("tone") or "")
    if tone:
        lines.append("Nada judul: %s" % esc(tone))
    lines.append("Sumber: %s" % source_line(draft))
    detail = "Isi: %d kata, %d bagian, %d gambar di isi" % (info["words"], info["sections"], info["inline"])
    if info["glossary"]:
        detail += ", glosarium %d istilah" % info["glossary"]
    lines.append(detail)
    lines.append("Gambar utama: %s" % ("ada" if info["featured"] else "belum ada"))
    report = article_generator.seo_report(article, (draft.get("wp") or {}).get("slug") or wxr_builder.slug_for(draft))
    if report["keyword"]:
        checks = [("judul", report["in_title"]), ("paragraf awal", report["in_intro"]), ("subjudul isi", report["in_heading"]), ("slug", report["in_slug"]), ("meta", report["in_meta"])]
        missing = [name for name, ok in checks if not ok]
        lines.append(
            "SEO: kata kunci <i>%s</i>, muncul %dx, link internal %d, link luar %d. %s"
            % (
                esc(report["keyword"]),
                report["count"],
                report["internal"],
                report["external"],
                "Belum ada di: %s." % ", ".join(missing) if missing else "Posisi kata kunci lengkap.",
            )
        )
    if wp.get("post_id"):
        lines.append("WordPress: %s, ID %s" % (STATUS_LABELS.get(wp.get("status"), wp.get("status")), wp["post_id"]))
        if wp.get("seo") and wp["seo"] != "ok":
            lines.append("Pengaturan SEO Yoast belum terisi, isi manual di editor.")
    else:
        lines.append("WordPress: belum dikirim")
    lines.append("")
    lines.append("Mau ubah sesuatu? Balas pesan ini dengan permintaanmu, misalnya <i>bagian kedua dipersingkat</i> atau <i>tambahin tips soal backup</i>.")
    return "\n".join(lines)


def card_keyboard(draft, wp_ready):
    wp = draft.get("wp") or {}
    rows = []
    if wp.get("post_id"):
        view = InlineKeyboardButton("Lihat artikel", url=wp["link"]) if wp.get("status") == "publish" else InlineKeyboardButton("Pratinjau", url=wp["preview"])
        rows.append([InlineKeyboardButton("Edit di WordPress", url=wp["admin_edit"]), view])
    rows.append([InlineKeyboardButton("Pilih judul", callback_data=cb(draft["id"], "tt")), InlineKeyboardButton("Lihat isi", callback_data=cb(draft["id"], "v"))])
    rows.append([InlineKeyboardButton("Revisi lewat chat", callback_data=cb(draft["id"], "e")), InlineKeyboardButton("Gambar utama", callback_data=cb(draft["id"], "g"))])
    last = []
    if wp.get("post_id"):
        if wp.get("status") == "publish":
            last.append(InlineKeyboardButton("Tarik jadi draf", callback_data=cb(draft["id"], "dr")))
        else:
            last.append(InlineKeyboardButton("Publish", callback_data=cb(draft["id"], "p")))
    elif wp_ready:
        last.append(InlineKeyboardButton("Kirim ke WordPress", callback_data=cb(draft["id"], "w")))
    last.append(InlineKeyboardButton("File XML", callback_data=cb(draft["id"], "x")))
    rows.append(last)
    if draft.get("history"):
        rows.append([InlineKeyboardButton("Batalkan perubahan terakhir", callback_data=cb(draft["id"], "u"))])
    return InlineKeyboardMarkup(rows)


def titles_text(draft):
    article = draft["article"]
    lines = ["<b>Pilih judul</b>", "Tiap opsi punya nada dan subjudul sendiri.", ""]
    for index, option in enumerate(article.get("title_options") or []):
        active = " (dipakai)" if option["title"] == article["title"] else ""
        if article.get("focus_keyword") and not article_generator.has_keyword(option["title"], article["focus_keyword"]):
            active += " <i>tanpa kata kunci</i>"
        label = article_generator.TONE_LABELS.get(option["tone"], option["tone"])
        lines.append("<b>%d. %s</b>%s" % (index + 1, esc(label), active))
        lines.append(esc(option["title"]))
        if option.get("subtitle"):
            lines.append("<i>%s</i>" % esc(option["subtitle"]))
        lines.append("")
    return "\n".join(lines).strip()


def titles_keyboard(draft):
    article = draft["article"]
    buttons = []
    for index, option in enumerate(article.get("title_options") or []):
        mark = " aktif" if option["title"] == article["title"] else ""
        buttons.append(InlineKeyboardButton("%d%s" % (index + 1, mark), callback_data=cb(draft["id"], "t", index)))
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton("Judul lain", callback_data=cb(draft["id"], "tn")), InlineKeyboardButton("Tutup", callback_data=cb(draft["id"], "close"))])
    return InlineKeyboardMarkup(rows)


def featured_keyboard(draft, candidates):
    buttons = []
    for index, img in enumerate(candidates):
        mark = " aktif" if img["role"] == "featured" else ""
        buttons.append(InlineKeyboardButton("%d%s" % (index + 1, mark), callback_data=cb(draft["id"], "gf", img["key"])))
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton("Tutup", callback_data=cb(draft["id"], "close"))])
    return InlineKeyboardMarkup(rows)


def candidate_caption(index, img):
    note = img.get("note") or {}
    origin = {"thumbnail": "thumbnail video", "user": "foto kiriman kamu", "requested": "frame pilihanmu"}.get(img.get("origin"), "menit %s" % img.get("label"))
    text = "%d. %s" % (index + 1, origin)
    if note.get("cover_score"):
        text += ", skor sampul %d dari 10" % round(note["cover_score"])
    return text


def confirm_keyboard(draft_id, yes_action, yes_label):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(yes_label, callback_data=cb(draft_id, yes_action)), InlineKeyboardButton("Batal", callback_data=cb(draft_id, "close"))]]
    )


def after_edit_keyboard(draft, conflict=False):
    wp = draft.get("wp") or {}
    rows = []
    if conflict:
        rows.append([InlineKeyboardButton("Timpa versi di WordPress", callback_data=cb(draft["id"], "ws"))])
    rows.append([InlineKeyboardButton("Lihat isi", callback_data=cb(draft["id"], "v")), InlineKeyboardButton("Batalkan", callback_data=cb(draft["id"], "u"))])
    if wp.get("post_id"):
        rows.append([InlineKeyboardButton("Pratinjau", url=wp["preview"]), InlineKeyboardButton("Menu draf", callback_data=cb(draft["id"], "card"))])
    else:
        rows.append([InlineKeyboardButton("Menu draf", callback_data=cb(draft["id"], "card"))])
    return InlineKeyboardMarkup(rows)


def preview_chunks(draft):
    article = draft["article"]
    images = {img["key"]: img for img in draft["images"]}
    parts = ["<b>%s</b>" % esc(article["title"])]
    if article.get("subtitle"):
        parts.append("<i>%s</i>" % esc(article["subtitle"]))
    featured = next((img for img in draft["images"] if img["role"] == "featured"), None)
    if featured:
        parts.append("[Gambar utama: %s]" % esc(featured.get("alt") or featured["key"]))
    summary = ["<b>%s</b>" % esc(wxr_builder.SUMMARY_HEADINGS.get(draft["kind"], "Ringkasan")), rich(article["summary"]["text"])]
    summary += ["• %s" % rich(p) for p in article["summary"]["points"]]
    parts.append("\n".join(summary))
    for number, section in enumerate(article["sections"], start=1):
        block_lines = ["<b>Bagian %d. %s</b>" % (number, esc(section["heading"]))]
        if section.get("image") and section["image"] in images:
            img = images[section["image"]]
            block_lines.append("[Gambar %s: %s]" % (esc(img["key"]), esc(img.get("caption") or img.get("alt"))))
        for block in section["blocks"]:
            if block["type"] == "list":
                block_lines += ["• %s" % rich(i) for i in block["items"]]
            elif block["type"] == "steps":
                block_lines += ["%d) %s" % (n + 1, rich(i)) for n, i in enumerate(block["items"])]
            elif block["type"] == "quote":
                by = " (%s)" % esc(block["by"]) if block.get("by") else ""
                block_lines.append('<blockquote>"%s"%s</blockquote>' % (esc(block["text"]), by))
            elif block["type"] == "callout":
                block_lines.append("<b>Catatan:</b> %s" % rich(block["text"]))
            else:
                block_lines.append(rich(block["text"]))
        parts.append("\n\n".join(block_lines))
    closing = ["<b>%s</b>" % esc(article["conclusion"]["heading"])] + [rich(p) for p in article["conclusion"]["paragraphs"]]
    parts.append("\n\n".join(closing))
    if article.get("cta"):
        parts.append("<b>Ajakan:</b> %s" % rich(article["cta"]))
    if article["glossary"]:
        parts.append("\n".join(["<b>Glosarium</b>"] + ["• <b>%s</b>: %s" % (esc(g["term"]), rich(g["definition"])) for g in article["glossary"]]))
    meta = "<i>Meta description: %s\nKata kunci: %s | Kategori: %s | Tag: %s</i>" % (
        esc(article.get("excerpt")),
        esc(article.get("focus_keyword")),
        esc(article.get("category")),
        esc(", ".join(article.get("tags") or [])),
    )
    parts.append(meta)
    chunks = []
    current = ""
    pieces = []
    for part in parts:
        pieces.extend([part] if len(part) <= LIMIT else part.split("\n\n"))
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > LIMIT:
            chunks.append(current)
            current = piece
        else:
            current = "%s\n\n%s" % (current, piece) if current else piece
    if current:
        chunks.append(current)
    return chunks


def progress_text(title, steps, failed=None):
    lines = ["<b>%s</b>" % esc(title), ""]
    for index, step in enumerate(steps):
        if index < len(steps) - 1:
            lines.append("selesai: %s" % esc(step))
        elif failed:
            lines.append("<b>gagal di: %s</b>" % esc(step))
        else:
            lines.append("<b>sedang: %s</b>" % esc(step))
    if failed:
        lines += ["", failed]
    return "\n".join(lines)
