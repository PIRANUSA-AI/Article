import json
from pathlib import Path

import qwen_client

KINDS = ("layar_aplikasi", "diagram", "gambar_teknis", "produk", "slide", "thumbnail", "foto_lapangan", "orang_bicara", "transisi", "lainnya")
WEAK_KINDS = ("orang_bicara", "transisi", "lainnya")
BATCH = 6


def _stats(path):
    from PIL import Image, ImageFilter, ImageStat

    with Image.open(path) as img:
        img = img.convert("RGB")
        width, height = img.size
        gray = img.convert("L").resize((320, int(320 * height / max(1, width)) or 1))
        stat = ImageStat.Stat(gray)
        edges = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES))
        small = img.convert("L").resize((9, 8))
        pixels = list(small.getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                bits = (bits << 1) | (1 if pixels[row * 9 + col] > pixels[row * 9 + col + 1] else 0)
    return {
        "width": width,
        "height": height,
        "brightness": stat.mean[0],
        "contrast": stat.stddev[0],
        "detail": edges.mean[0],
        "hash": bits,
    }


def _distance(a, b):
    return bin(a ^ b).count("1")


def prefilter(frames, keep=8):
    kept = []
    for frame in frames:
        path = Path(frame["path"])
        try:
            stats = _stats(path)
        except Exception:
            continue
        if stats["brightness"] < 22 or stats["contrast"] < 14 or stats["detail"] < 4:
            continue
        frame = dict(frame, stats=stats)
        duplicate = None
        for index, other in enumerate(kept):
            if _distance(other["stats"]["hash"], stats["hash"]) <= 10:
                duplicate = index
                break
        if duplicate is None:
            kept.append(frame)
        elif stats["detail"] > kept[duplicate]["stats"]["detail"]:
            kept[duplicate] = frame
    kept.sort(key=lambda f: f["stats"]["detail"], reverse=True)
    kept = kept[:keep]
    kept.sort(key=lambda f: f.get("seconds") or 0)
    return kept


def describe(path):
    try:
        return _stats(Path(path))
    except Exception:
        return None


def _prompt(context, mode):
    if mode == "source":
        task = (
            "Gambar gambar ini dikirim user sebagai bahan utama artikel blog. "
            "Untuk tiap gambar, catat semua fakta yang benar benar terlihat: teks di layar (salin persis), angka, nama produk, "
            "menu atau tombol, objek, kondisi, dan konteks. Jangan menebak hal yang tidak terlihat."
        )
    else:
        task = (
            "Gambar gambar ini adalah cuplikan dari sebuah video dan thumbnail videonya. "
            "Tugasmu menilai gambar mana yang layak dipakai di artikel blog tentang video itu."
        )
    return (
        "%s\n\nKonteks: %s\n\n"
        "Setiap gambar diawali label kode dalam kurung siku, misalnya [F1]. Pakai kode itu persis, jangan menomori ulang.\n\n"
        "Balas JSON: {\"images\": [{\"key\": string, \"kind\": salah satu dari %s, "
        "\"info_score\": 0 sampai 10 (seberapa banyak informasi yang membantu pembaca memahami topik, layar aplikasi yang jelas dan diagram tinggi, orang yang sedang bicara rendah), "
        "\"cover_score\": 0 sampai 10 (seberapa menarik sebagai gambar utama artikel: komposisi rapi, tajam, ada judul atau subjek jelas), "
        "\"readable\": true atau false (teks penting terbaca), "
        "\"description\": string (1 sampai 2 kalimat faktual), "
        "\"on_screen_text\": string (teks penting yang terlihat, salin persis, kosongkan kalau tidak ada), "
        "\"facts\": [string] (fakta konkret yang terlihat, maksimal 8), "
        "\"alt\": string (alt text bahasa Indonesia maksimal 120 karakter, deskriptif, tanpa kata gambar dari), "
        "\"caption\": string (keterangan singkat yang enak dibaca, maksimal 90 karakter, tanpa tanda hubung dan titik koma)}], "
        "\"summary\": string}"
    ) % (task, context, json.dumps(KINDS))


def analyze(entries, context, mode="frames"):
    notes = {}
    summary = []
    models_used = []
    errors = []
    for start in range(0, len(entries), BATCH):
        batch = entries[start : start + BATCH]
        parts = [_prompt(context, mode)]
        for entry in batch:
            parts.append("[%s] %s" % (entry["key"], entry.get("label") or ""))
            parts.append({"image": Path(entry["path"])})
        try:
            raw, model = qwen_client.vision_parts(parts, json_mode=True, max_tokens=3000, temperature=0.2)
            data = qwen_client.parse_json(raw)
        except Exception as exc:
            errors.append(str(exc)[:200])
            continue
        models_used.append(model)
        valid = {entry["key"] for entry in batch}
        items = data.get("images") or []
        for position, item in enumerate(items):
            key = str(item.get("key") or "").strip().strip("[]").upper()
            if key not in valid and position < len(batch):
                key = batch[position]["key"]
            if key not in valid:
                continue
            notes[key] = _clean_note(item)
        if data.get("summary"):
            summary.append(str(data["summary"]))
    return {"notes": notes, "summary": " ".join(summary), "models": models_used, "errors": errors}


def _score(value):
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _clean_note(item):
    kind = str(item.get("kind") or "lainnya").strip().lower()
    if kind not in KINDS:
        kind = "lainnya"
    facts = [str(f).strip() for f in (item.get("facts") or []) if str(f).strip()][:8]
    return {
        "kind": kind,
        "info_score": _score(item.get("info_score")),
        "cover_score": _score(item.get("cover_score")),
        "readable": bool(item.get("readable", True)),
        "description": str(item.get("description") or "").strip(),
        "on_screen_text": str(item.get("on_screen_text") or "").strip(),
        "facts": facts,
        "alt": str(item.get("alt") or "").strip()[:125],
        "caption": str(item.get("caption") or "").strip()[:120],
    }


def choose_featured(entries, notes, prefer_keys=()):
    for key in prefer_keys:
        entry = next((e for e in entries if e["key"] == key), None)
        if not entry:
            continue
        note = notes.get(key)
        stats = entry.get("stats") or describe(entry["path"]) or {}
        if stats.get("width", 0) < 600:
            continue
        if note and note["cover_score"] < 4 and note["kind"] in WEAK_KINDS:
            continue
        return entry
    ranked = sorted(
        entries,
        key=lambda e: (notes.get(e["key"], {}).get("cover_score", 0), notes.get(e["key"], {}).get("info_score", 0)),
        reverse=True,
    )
    return ranked[0] if ranked else None


def choose_inline(entries, notes, exclude, limit, min_score=6):
    featured_hashes = [
        (e.get("stats") or {}).get("hash") for e in entries if e["key"] in exclude and (e.get("stats") or {}).get("hash") is not None
    ]
    pool = []
    for entry in entries:
        if entry["key"] in exclude:
            continue
        note = notes.get(entry["key"])
        if not note:
            continue
        if note["kind"] in WEAK_KINDS or note["kind"] == "thumbnail":
            continue
        if note["info_score"] < min_score or not note["readable"]:
            continue
        entry_hash = (entry.get("stats") or {}).get("hash")
        if entry_hash is not None and any(_distance(entry_hash, h) <= 10 for h in featured_hashes):
            continue
        pool.append(entry)
    pool.sort(key=lambda e: notes[e["key"]]["info_score"], reverse=True)
    picked = []
    for entry in pool:
        entry_hash = (entry.get("stats") or {}).get("hash")
        if entry_hash is not None and any(_distance(entry_hash, (p.get("stats") or {}).get("hash", 0)) <= 12 for p in picked):
            continue
        picked.append(entry)
        if len(picked) >= limit:
            break
    return picked
