import html
import re
import threading
import time
from pathlib import Path

import config
import humanizer
import qwen_client
import utils_text
import wordpress_push

POST_TYPE = "testimoni"
TAXONOMY = "produk_terkait"
FIELD_QUOTE = "field_pir_tm_kutipan"
FIELD_COMPANY = "field_pir_tm_perusahaan"
FIELD_ROLE = "field_pir_tm_peran"
FIELD_VIDEO = "field_pir_tm_video"
FIELD_HOME = "field_pir_tm_home"
TITLE_HINT = re.compile(r"\btesti(moni|monial)?\b", re.IGNORECASE)
TAG_RE = re.compile(r"<(input|textarea|select)\b([^>]*)>", re.IGNORECASE)
OPTION_RE = re.compile(r"<option\b([^>]*)>", re.IGNORECASE)
KNOWN_TTL = 1800
_known = {"at": 0, "site": "", "videos": {}}
_known_lock = threading.Lock()

DETECT_SYSTEM = (
    "Kamu memeriksa apakah sebuah video YouTube dari channel %s adalah video TESTIMONI pelanggan. "
    "Testimoni berarti isi utamanya adalah perwakilan perusahaan atau pengguna nyata yang menceritakan pengalaman mereka memakai "
    "software atau layanan yang dijual %s, misalnya wawancara klien, studi kasus pelanggan, atau kompilasi komentar pengguna. "
    "BUKAN testimoni: tutorial fitur, webinar, liputan pameran atau booth, profil perusahaan %s sendiri, promo produk, "
    "walaupun ada satu dua pengunjung yang berkomentar singkat. "
    'Balas JSON: {"testimonial": true atau false, "reason": "satu kalimat"}'
) % (config.SITE_TITLE, config.SITE_TITLE, config.SITE_TITLE)

EXTRACT_SYSTEM = (
    "Kamu menyiapkan entri modul Testimoni untuk situs %s dari transkrip video testimoni pelanggan. "
    "Satu entri untuk tiap perusahaan pelanggan yang benar benar berbicara di video, paling banyak 6 entri. "
    "Aturan tiap entri:\n"
    "company: nama resmi perusahaan pelanggan seperti yang disebut di judul, deskripsi, atau transkrip, misalnya PT Beton Elemenindo Perkasa. Jangan pernah %s.\n"
    "person: nama pembicara kalau disebut jelas, kalau tidak ada isi string kosong. Jangan mengarang nama.\n"
    "role: jabatan atau divisi pembicara kalau disebut, kalau tidak ada isi string kosong.\n"
    "quote: 2 sampai 3 kalimat, 35 sampai 70 kata, sudut pandang orang pertama jamak (kami), merangkum masalah yang mereka hadapi "
    "dan hasil yang mereka rasakan setelah memakai produk. Setia pada isi transkrip, rapikan bahasa lisan jadi kalimat baku yang enak dibaca, "
    "jangan menambah angka atau klaim yang tidak diucapkan.\n"
    "product: tepat satu nama dari DAFTAR PRODUK yang paling sesuai dengan software yang dibahas, atau string kosong kalau tidak ada yang cocok.\n"
    "Karakter terlarang: em dash, en dash, tanda hubung, titik koma, emoji, kutip melengkung.\n"
    'Balas JSON: {"testimonials": [{"company": "...", "person": "...", "role": "...", "quote": "...", "product": "..."}]}'
) % (config.SITE_TITLE, config.SITE_TITLE)


class TestimonialError(RuntimeError):
    pass


def _material(video_info, transcript_text, limit, note=""):
    extra = "CATATAN USER (nama perusahaan atau pembicara yang tampil di video):\n%s\n\n" % note if note else ""
    return "%sJUDUL: %s\nCHANNEL: %s\nDESKRIPSI:\n%s\n\nTRANSKRIP:\n%s" % (
        extra,
        video_info.get("title") or "",
        video_info.get("channel") or "",
        (video_info.get("description") or "")[:1500],
        (transcript_text or "")[:limit],
    )


def detect(video_info, transcript_text):
    if TITLE_HINT.search(video_info.get("title") or ""):
        return True
    try:
        data, _ = qwen_client.chat_json(
            DETECT_SYSTEM,
            _material(video_info, transcript_text, 6000),
            models=qwen_client.fast_models(),
            temperature=0.0,
            max_tokens=200,
        )
    except Exception:
        return False
    return isinstance(data, dict) and data.get("testimonial") is True


def extract(video_info, transcript_text, products, note=""):
    menu = ", ".join(products) or "(kosong)"
    prompt = "DAFTAR PRODUK: %s\n\n%s" % (menu, _material(video_info, transcript_text, 24000, note))
    data, _ = qwen_client.chat_json(EXTRACT_SYSTEM, prompt, temperature=0.3, max_tokens=2400)
    items = (data or {}).get("testimonials") if isinstance(data, dict) else None
    lookup = {name.lower(): name for name in products}
    out = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        company = humanizer.sanitize(item.get("company"))
        quote = humanizer.sanitize(item.get("quote"))
        if not company or not quote or company.lower() in seen:
            continue
        seen.add(company.lower())
        person = humanizer.sanitize(item.get("person"))
        role = humanizer.sanitize(item.get("role"))
        out.append(
            {
                "company": company[:160],
                "person": person[:80],
                "role": role[:80],
                "quote": quote[:900],
                "product": lookup.get(str(item.get("product") or "").strip().lower(), ""),
            }
        )
    if not out:
        raise TestimonialError(
            "Video ini testimoni, tapi nama perusahaan pelanggannya tidak disebut di transkrip maupun deskripsi. "
            "Kirim ulang linknya sambil menulis nama perusahaan dan pembicaranya, misalnya: link lalu PT Contoh Jaya, Budi, Drafter."
        )
    return out[:6]


def role_line(entry):
    return ", ".join(part for part in (entry.get("person"), entry.get("role")) if part)


def products(client):
    resp = client.api("GET", TAXONOMY, params={"per_page": 100})
    if resp.status_code != 200:
        return {}
    return {html.unescape(item.get("name") or "").strip(): item["id"] for item in resp.json()}


def _edit_page(client, post_id):
    resp = client.session.get(
        client.base + "/wp-admin/post.php", params={"post": int(post_id), "action": "edit"}, timeout=config.REQUEST_TIMEOUT * 2
    )
    if resp.status_code != 200:
        raise TestimonialError("editor testimoni %s tidak bisa dibuka (HTTP %d)" % (post_id, resp.status_code))
    return resp.text


def _attrs(raw):
    return {
        m.group(1).lower(): html.unescape(m.group(2) if m.group(2) is not None else m.group(3))
        for m in wordpress_push.ATTR_RE.finditer(raw)
    }


def _flag(raw, name):
    if name in _attrs(raw):
        return True
    return re.search(r"\b%s\b" % name, wordpress_push.ATTR_RE.sub("", raw), re.IGNORECASE) is not None


def form_fields(page):
    start = page.find('<form name="post"')
    if start < 0:
        raise TestimonialError("form editor klasik tidak ditemukan")
    fragment = page[start : page.find("</form>", start)]
    fields = []
    for match in TAG_RE.finditer(fragment):
        tag, raw = match.group(1).lower(), match.group(2)
        attrs = _attrs(raw)
        name = attrs.get("name")
        if not name:
            continue
        if tag == "input":
            kind = attrs.get("type", "text").lower()
            if kind in ("submit", "button", "file", "image", "reset"):
                continue
            if kind in ("checkbox", "radio") and not _flag(raw, "checked"):
                continue
            fields.append((name, attrs.get("value", "on" if kind == "checkbox" else "")))
        elif tag == "textarea":
            end = fragment.find("</textarea>", match.end())
            fields.append((name, html.unescape(fragment[match.end() : end])))
        else:
            end = fragment.find("</select>", match.end())
            chosen = None
            for option in OPTION_RE.finditer(fragment[match.end() : end]):
                values = _attrs(option.group(1))
                if chosen is None or _flag(option.group(1), "selected"):
                    chosen = values.get("value", "")
                    if _flag(option.group(1), "selected"):
                        break
            if chosen is not None:
                fields.append((name, chosen))
    return fields


def read_video_field(page):
    match = re.search(r'name="acf\[%s\]"[^>]*value="([^"]*)"' % FIELD_VIDEO, page)
    return html.unescape(match.group(1)) if match else ""


def known_videos(client, refresh=False):
    with _known_lock:
        fresh = time.time() - _known["at"] < KNOWN_TTL and _known["site"] == client.base
        if fresh and not refresh:
            return dict(_known["videos"])
    found = {}
    page_no = 1
    while True:
        resp = client.api(
            "GET", POST_TYPE, params={"per_page": 100, "page": page_no, "status": "publish,draft,pending,private,future", "context": "edit"}
        )
        if resp.status_code != 200:
            break
        items = resp.json()
        for item in items:
            try:
                video_id = utils_text.extract_video_id(read_video_field(_edit_page(client, item["id"])))
            except Exception:
                continue
            if video_id:
                found.setdefault(video_id, item["id"])
        if len(items) < 100:
            break
        page_no += 1
    with _known_lock:
        _known.update({"at": time.time(), "site": client.base, "videos": found})
    return dict(found)


def _save_fields(client, post_id, entry, video_url):
    page = _edit_page(client, post_id)
    data = [(name, value) for name, value in form_fields(page) if not name.startswith("acf[")]
    if not any(name == "_acf_nonce" for name, _ in data):
        raise TestimonialError("nonce ACF tidak ditemukan di editor testimoni")
    data = [
        (name, value)
        for name, value in data
        if name not in ("post_title", "_acf_changed", "save", "publish") and not name.startswith(("new" + TAXONOMY, "_ajax_nonce"))
    ]
    data += [
        ("post_title", entry["company"]),
        ("_acf_changed", "1"),
        ("acf[%s]" % FIELD_QUOTE, entry["quote"]),
        ("acf[%s]" % FIELD_COMPANY, entry["company"]),
        ("acf[%s]" % FIELD_ROLE, role_line(entry)),
        ("acf[%s]" % FIELD_VIDEO, video_url),
        ("acf[%s]" % FIELD_HOME, "0"),
        ("save", "Save Draft"),
    ]
    resp = client.session.post(client.base + "/wp-admin/post.php", data=data, timeout=config.REQUEST_TIMEOUT * 2)
    if resp.status_code not in (200, 302):
        raise TestimonialError("simpan field testimoni gagal (HTTP %d)" % resp.status_code)
    check = _edit_page(client, post_id)
    if utils_text.extract_video_id(read_video_field(check)) != utils_text.extract_video_id(video_url):
        raise TestimonialError("field testimoni tidak tersimpan, cek manual di editor")


def _say(on_progress, message):
    if on_progress:
        try:
            on_progress(message)
        except Exception:
            pass


def push(draft, values, on_progress=None):
    client = wordpress_push.client_for(values)
    source = draft.get("source") or {}
    video_url = source.get("url") or ""
    if source.get("video_id") and not any(entry.get("post_id") for entry in draft["testimonials"]):
        existing = known_videos(client).get(source["video_id"])
        if existing:
            raise TestimonialError(
                "Video ini sudah ada di modul Testimoni (ID %s): %s/wp-admin/post.php?post=%s&action=edit" % (existing, client.base, existing)
            )
    terms = products(client)
    cover = next((img for img in draft.get("images") or [] if img.get("role") == "featured"), None)
    if cover and not cover.get("media_id") and cover.get("path") and Path(cover["path"]).exists():
        _say(on_progress, "Upload thumbnail testimoni...")
        company = draft["testimonials"][0]["company"]
        name = "_".join(["testi"] + re.findall(r"[a-z0-9]+", company.lower()))[:60]
        uploaded = client.upload_media(cover["path"], company, "", "Testimoni %s" % company, name + ".jpg")
        cover["media_id"] = uploaded["id"]
        cover["url"] = uploaded["url"]
    for index, entry in enumerate(draft["testimonials"]):
        if entry.get("post_id"):
            continue
        _say(on_progress, "Kirim testimoni %d dari %d ke WordPress..." % (index + 1, len(draft["testimonials"])))
        payload = {"title": entry["company"], "status": "draft"}
        if cover and cover.get("media_id"):
            payload["featured_media"] = cover["media_id"]
        if terms.get(entry.get("product")):
            payload[TAXONOMY] = [terms[entry["product"]]]
        resp = client.api("POST", POST_TYPE, json=payload)
        if resp.status_code not in (200, 201):
            raise TestimonialError("gagal bikin testimoni (HTTP %d): %s" % (resp.status_code, resp.text[:200]))
        post = resp.json()
        entry.update(
            {
                "post_id": post["id"],
                "status": post.get("status"),
                "admin_edit": "%s/wp-admin/post.php?post=%s&action=edit" % (client.base, post["id"]),
                "preview": "%s/?p=%s&preview=true" % (client.base, post["id"]),
            }
        )
        try:
            _save_fields(client, post["id"], entry, video_url)
            entry["fields"] = "ok"
        except Exception as exc:
            entry["fields"] = str(exc)[:200]
    with _known_lock:
        if source.get("video_id") and _known["site"] == client.base:
            _known["videos"][source["video_id"]] = draft["testimonials"][0].get("post_id")
    draft["wp"] = {"site": client.base, "post_id": draft["testimonials"][0].get("post_id"), "status": "draft"}
    return draft["testimonials"]
