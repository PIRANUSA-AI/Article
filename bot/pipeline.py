import json
import re
import shutil
from pathlib import Path

import article_generator
import config
import drafts
import humanizer
import image_picker
import sipira
import site_links
import transcript_source
import video_source
import wxr_builder


class PipelineError(RuntimeError):
    pass


FEATURED_HINT = re.compile(r"\b(gambar utama|cover|thumbnail|featured|sampul)\b", re.IGNORECASE)


def _say(callback, message):
    if callback:
        try:
            callback(message)
        except Exception:
            pass


def _normalize_image(src, dest, max_width=1600):
    from PIL import Image, ImageOps

    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        if img.width > max_width:
            ratio = max_width / float(img.width)
            img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
        img.save(dest, "JPEG", quality=86, optimize=True, progressive=True)
        return {"path": str(dest), "width": img.width, "height": img.height}


def _mmss(seconds):
    seconds = int(seconds or 0)
    return "%02d:%02d" % (seconds // 60, seconds % 60)


def _transcript_cache(video_id):
    return config.CACHE_DIR / ("transcript_%s.json" % re.sub(r"[^\w]", "_", video_id))


def _combine_brief(brief, caption):
    parts = [p.strip() for p in (brief, caption) if p and p.strip()]
    return "\n".join(parts) or None


def create(video_id=None, image_paths=None, text=None, caption=None, brief=None, frame_seconds=None, owner=None, on_progress=None):
    kind = "video" if video_id else ("image" if image_paths else "text")
    if kind == "text" and not (text or "").strip():
        raise PipelineError("tidak ada bahan untuk ditulis")
    draft_id = drafts.new_id()
    work_dir = config.JOBS_DIR / ("%s_%s" % (video_id or kind, draft_id))
    work_dir.mkdir(parents=True, exist_ok=True)
    caption = (caption or "").strip()
    entries = []
    source = {"type": kind}
    source_title = ""
    material = ""

    if kind == "video":
        _say(on_progress, "Baca data video...")
        video_info = video_source.probe(video_id)
        source.update({k: video_info.get(k) for k in ("video_id", "url", "title", "channel", "duration", "upload_date")})
        source_title = video_info.get("title") or ""

        _say(on_progress, "Ambil transkrip...")
        transcript = transcript_source.fetch(video_id)
        snippets = transcript["snippets"]
        payload = json.dumps({"video": video_info, "transcript": transcript}, ensure_ascii=False)
        (work_dir / "transkrip.json").write_text(payload, encoding="utf-8")
        _transcript_cache(video_id).write_text(payload, encoding="utf-8")
        source["transcript"] = {"language": transcript.get("language"), "via": transcript.get("source"), "segments": len(snippets)}

        _say(on_progress, "Ambil cuplikan dari video...")
        requested = None
        if frame_seconds:
            try:
                requested = video_source.frame_at(video_info, frame_seconds, work_dir)
            except Exception:
                requested = None
        try:
            frames = video_source.grab_frames(video_info, work_dir)
        except Exception:
            frames = []
        frames = image_picker.prefilter(frames)
        if requested:
            entries.append(
                {"key": "R1", "path": str(requested["path"]), "label": _mmss(requested["seconds"]), "origin": "requested",
                 "seconds": requested["seconds"], "stats": image_picker.describe(requested["path"])}
            )
        for index, frame in enumerate(frames):
            entries.append(
                {"key": "F%d" % (index + 1), "path": str(frame["path"]), "label": _mmss(frame["seconds"]), "origin": "frame",
                 "seconds": frame["seconds"], "stats": frame.get("stats")}
            )
        thumbnail = video_source.download_thumbnail(video_info, work_dir)
        if thumbnail:
            entries.append(
                {"key": "T1", "path": str(thumbnail), "label": "thumbnail video", "origin": "thumbnail",
                 "stats": image_picker.describe(thumbnail)}
            )

        language = transcript_source.language_hint(video_info, snippets)
        if sum(len(s["text"]) for s in snippets) > config.QWEN_CHUNK_CHARS:
            _say(on_progress, "Transkrip panjang, diringkas per bagian dulu...")
        transcript_text = article_generator.condense_transcript(snippets)
        material = article_generator.material_for_video(video_info, transcript_text, language)

    for index, raw_path in enumerate(image_paths or []):
        dest = work_dir / ("user_%02d.jpg" % (index + 1))
        try:
            info = _normalize_image(raw_path, dest)
        except Exception as exc:
            raise PipelineError("gambar %d tidak bisa dibaca: %s" % (index + 1, exc))
        entries.append(
            {"key": "U%d" % (index + 1), "path": info["path"], "label": "foto kiriman user", "origin": "user",
             "stats": image_picker.describe(info["path"])}
        )

    notes = {}
    if entries:
        _say(on_progress, "Membaca %d gambar..." % len(entries))
        if kind == "video":
            context = 'video "%s" dari channel %s' % (source.get("title"), source.get("channel"))
        else:
            context = caption or "gambar kiriman user untuk artikel blog %s" % config.SITE_TITLE
        analysis = image_picker.analyze(entries, context, mode="source" if kind == "image" else "frames")
        notes = analysis["notes"]
        (work_dir / "image_notes.json").write_text(
            json.dumps({"entries": [{k: v for k, v in e.items() if k != "stats"} for e in entries], **analysis}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        if kind == "image" and not notes:
            raise PipelineError("gambar gagal dibaca: %s" % "; ".join(analysis["errors"])[:300])

    if kind == "image":
        material = article_generator.material_for_images([e for e in entries if e["origin"] == "user"], notes, caption)
    elif kind == "text":
        material = article_generator.material_for_text(text)
        brief = _combine_brief(brief, caption)
    else:
        brief = _combine_brief(brief, caption)

    featured, offered = _plan_images(kind, entries, notes)

    links = _links_for(source, material, caption)
    _say(on_progress, "Menulis artikel...")
    article = article_generator.write(kind, material, source_title, offered, notes, brief, links=links)

    images = []
    for entry in entries:
        role = "featured" if featured and entry["key"] == featured["key"] else "spare"
        images.append(_image_record(entry, notes.get(entry["key"]), role, article["title"], work_dir))

    draft = {
        "id": draft_id,
        "owner": owner,
        "kind": kind,
        "created": drafts.now(),
        "work_dir": str(work_dir),
        "source": source,
        "caption": caption,
        "brief": brief,
        "article": article,
        "images": images,
        "wp": {},
        "history": [],
    }
    _say(on_progress, "Bikin tombol CTA...")
    draft["cta_url"] = sipira.cta_url(wxr_builder.slug_for(draft), article.get("title"))
    (work_dir / "material.txt").write_text(material, encoding="utf-8")
    keyword_alt(draft)
    write_markdown(draft)
    drafts.save(draft)
    return draft


def _links_for(source, material, caption):
    text = " ".join(filter(None, [source.get("title"), caption, (material or "")[:3000]]))
    try:
        internal = site_links.related(text, 10)
    except Exception:
        internal = []
    extra = [source["url"]] if source.get("url") else []
    return {"internal": internal, "external": site_links.external_from(material, extra)}


def keyword_alt(draft):
    keyword = draft["article"].get("focus_keyword")
    featured = next((img for img in draft["images"] if img["role"] == "featured"), None)
    if not keyword or not featured:
        return
    if not article_generator.has_keyword(featured.get("alt"), keyword):
        alt = featured.get("alt") or draft["article"]["title"]
        featured["alt"] = ("%s, %s" % (keyword, alt[:1].lower() + alt[1:]))[:125]


def _plan_images(kind, entries, notes):
    limit = config.MAX_INLINE_IMAGES
    users = [e for e in entries if e["origin"] == "user"]
    by_cover = sorted(users, key=lambda e: notes.get(e["key"], {}).get("cover_score", 0), reverse=True)
    if users:
        featured = image_picker.choose_featured(users, notes, prefer_keys=[e["key"] for e in by_cover])
    elif any(e["origin"] == "thumbnail" for e in entries):
        featured = image_picker.choose_featured(entries, notes, prefer_keys=["T1"])
    else:
        featured = image_picker.choose_featured(entries, notes)
    exclude = {featured["key"]} if featured else set()

    offered = []
    for entry in entries:
        if entry["origin"] in ("requested", "user") and entry["key"] not in exclude:
            offered.append(entry)
    if kind != "image":
        pool = [e for e in entries if e["origin"] == "frame"]
        for entry in image_picker.choose_inline(pool, notes, exclude, limit + 2):
            if entry not in offered:
                offered.append(entry)
    return featured, offered[: limit + 3]


def _image_record(entry, note, role, fallback_title, work_dir):
    note = note or {}
    out = Path(work_dir) / ("img_%s.jpg" % entry["key"].lower())
    try:
        info = _normalize_image(entry["path"], out)
    except Exception:
        info = {"path": entry["path"], "width": 1280, "height": 720}
    alt = humanizer.sanitize(note.get("alt")) or fallback_title
    caption = humanizer.sanitize(note.get("caption"))
    return {
        "key": entry["key"],
        "origin": entry.get("origin"),
        "label": entry.get("label"),
        "seconds": entry.get("seconds"),
        "path": info["path"],
        "width": info["width"],
        "height": info["height"],
        "alt": alt[:125],
        "caption": caption[:120],
        "role": role,
        "note": note,
        "media_id": None,
        "url": None,
    }


def material(draft):
    path = Path(draft["work_dir"]) / "material.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _offer(draft):
    entries = []
    notes = {}
    for img in draft["images"]:
        if img.get("role") == "featured":
            continue
        note = img.get("note") or {}
        if img.get("origin") in ("user", "requested") or img["key"] in article_generator.inline_images(draft["article"]) or (
            note.get("info_score", 0) >= 5 and note.get("kind") not in image_picker.WEAK_KINDS + ("thumbnail",)
        ):
            entries.append({"key": img["key"], "path": img["path"], "label": img.get("label")})
            notes[img["key"]] = note
    return entries, notes


def write_markdown(draft):
    source_url = (draft.get("source") or {}).get("url")
    heading = wxr_builder.SUMMARY_HEADINGS.get(draft["kind"], "Ringkasan")
    text = article_generator.to_markdown(draft["article"], source_url, heading)
    path = Path(draft["work_dir"]) / "artikel.md"
    path.write_text(text, encoding="utf-8")
    return path


def revise(draft, instruction, new_image=None):
    entries, notes = _offer(draft)
    drafts.snapshot(draft, instruction[:60])
    article, note = article_generator.revise(draft["article"], instruction, material(draft), entries, notes, new_image=new_image)
    draft["article"] = article
    write_markdown(draft)
    drafts.save(draft)
    return note


def new_titles(draft):
    article = draft["article"]
    avoid = [o["title"] for o in article.get("title_options") or []]
    source_title = (draft.get("source") or {}).get("title") or ""
    options = article_generator.retitle(article, material(draft), source_title, avoid)
    if not options:
        raise PipelineError("Belum dapat judul baru yang cukup beda. Coba lagi.")
    current = next((o for o in article.get("title_options") or [] if o["title"] == article["title"]), None)
    article["title_options"] = ([current] if current else []) + options
    drafts.save(draft)
    return article["title_options"]


def choose_title(draft, index):
    drafts.snapshot(draft, "ganti judul")
    article_generator.apply_title(draft["article"], index)
    write_markdown(draft)
    drafts.save(draft)
    return draft["article"]["title"]


def set_featured(draft, key):
    target = next((img for img in draft["images"] if img["key"] == key), None)
    if not target:
        raise PipelineError("gambar %s tidak ada" % key)
    drafts.snapshot(draft, "ganti gambar utama")
    for img in draft["images"]:
        if img["role"] == "featured":
            img["role"] = "spare"
    target["role"] = "featured"
    for section in draft["article"]["sections"]:
        if section.get("image") == key:
            section["image"] = None
    keyword_alt(draft)
    write_markdown(draft)
    drafts.save(draft)
    return target


def featured_candidates(draft, limit=6):
    ranked = sorted(
        draft["images"],
        key=lambda img: (
            img["role"] == "featured",
            img.get("origin") in ("user", "thumbnail"),
            (img.get("note") or {}).get("cover_score", 0),
        ),
        reverse=True,
    )
    return ranked[:limit]


def add_image(draft, image_path, caption=""):
    work_dir = Path(draft["work_dir"])
    count = sum(1 for img in draft["images"] if img.get("origin") == "user") + 1
    key = "U%d" % count
    while any(img["key"] == key for img in draft["images"]):
        count += 1
        key = "U%d" % count
    dest = work_dir / ("user_%s.jpg" % key.lower())
    info = _normalize_image(image_path, dest)
    entry = {"key": key, "path": info["path"], "label": "foto kiriman user", "origin": "user", "stats": image_picker.describe(info["path"])}
    context = "%s. Artikel: %s" % (caption or "foto tambahan dari user", draft["article"]["title"])
    analysis = image_picker.analyze([entry], context, mode="source")
    note = analysis["notes"].get(key)
    record = _image_record(entry, note, "spare", draft["article"]["title"], work_dir)
    draft["images"].append(record)
    if caption and FEATURED_HINT.search(caption):
        set_featured(draft, key)
        return {"key": key, "featured": True, "note": "Foto baru dipakai sebagai gambar utama."}
    instruction = caption or "Tambahkan foto baru ini ke bagian yang paling cocok."
    change = revise(draft, instruction, new_image=key)
    placed = key in article_generator.inline_images(draft["article"])
    return {"key": key, "featured": False, "placed": placed, "note": change}


def undo(draft):
    label = drafts.undo(draft)
    if label is None:
        return None
    write_markdown(draft)
    drafts.save(draft)
    return label


def build_files(draft, public_base=""):
    out_dir = Path(draft["work_dir"])
    result = wxr_builder.build_package(draft, out_dir, public_base=public_base)
    result["markdown"] = str(write_markdown(draft))
    if public_base:
        publish_media(draft)
    return result


def publish_media(draft):
    target_dir = config.MEDIA_DIR / "files"
    target_dir.mkdir(parents=True, exist_ok=True)
    for position, img in enumerate(wxr_builder.ordered_images(draft)):
        path = Path(img.get("path") or "")
        if path.exists():
            shutil.copy(path, target_dir / wxr_builder.media_filename(draft, img, position))


def stats(draft):
    article = draft["article"]
    return {
        "words": article_generator.word_count(article),
        "inline": len(article_generator.inline_images(article)),
        "featured": any(img["role"] == "featured" for img in draft["images"]),
        "glossary": len(article["glossary"]),
        "sections": len(article["sections"]),
    }


def lookup_timestamps(video_id, keyword):
    store = _transcript_cache(video_id)
    if store.exists():
        data = json.loads(store.read_text(encoding="utf-8"))
        snippets = data["transcript"]["snippets"]
    else:
        transcript = transcript_source.fetch(video_id)
        store.write_text(json.dumps({"transcript": transcript}, ensure_ascii=False), encoding="utf-8")
        snippets = transcript["snippets"]
    return transcript_source.timed_lines(snippets, keyword)
