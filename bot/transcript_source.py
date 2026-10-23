import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

import config
import settings_store
import video_source
import utils_text


class TranscriptError(RuntimeError):
    pass


def _clean_text(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = (
        text.replace("&amp;", "&")
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _from_api(video_id):
    from youtube_transcript_api import YouTubeTranscriptApi

    init_kwargs = {}
    proxy = settings_store.proxy()
    if proxy:
        from youtube_transcript_api.proxies import ProxyConfig

        init_kwargs["proxy_config"] = ProxyConfig(http=proxy, https=proxy)
    api = YouTubeTranscriptApi(**init_kwargs)
    errors = []
    for kwargs in _api_variants():
        try:
            fetched = api.fetch(video_id, **kwargs)
        except Exception as exc:
            errors.append("%s -> %s" % (kwargs, type(exc).__name__))
            continue
        snippets = [
            {"start": float(s.start), "duration": float(s.duration), "text": _clean_text(s.text)}
            for s in fetched
            if _clean_text(getattr(s, "text", ""))
        ]
        if not snippets:
            errors.append("%s -> kosong" % kwargs)
            continue
        meta = getattr(fetched, "_meta", None) or {}
        return {
            "snippets": snippets,
            "language": getattr(fetched, "language", None) or meta.get("language_code") or "?",
            "source": "youtube-transcript-api",
        }
    raise TranscriptError("ytt-api: " + "; ".join(errors[-4:]))


def _api_variants():
    base = {"languages": config.TRANSCRIPT_LANGUAGES}
    yield dict(base)
    yield dict(base, languages=["en"])


def _from_ytdlp(video_id):
    url = utils_text.watch_url(video_id)
    outdir = Path(tempfile.mkdtemp(prefix="ytt_"))
    cmd = [
        sys.executable, "-m", "yt_dlp", "--skip-download", "--write-subs", "--write-auto-subs",
        "--sub-langs", ",".join(config.TRANSCRIPT_LANGUAGES + ["en.*", "id.*", ".*"]),
        "--sub-format", "json3/vtt/srt", "--convert-subs", "srt",
        "-o", str(outdir / "%(id)s.%(ext)s"), "--no-playlist", "--merge-output-format", "mp4",
    ]
    proxy = settings_store.proxy()
    if proxy:
        cmd += ["--proxy", proxy]
    cookies = settings_store.cookies_file()
    if cookies:
        cmd += ["--cookies", cookies]
    cmd.append(url)
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=config.TRANSCRIPT_TIMEOUT * 2)
    except Exception as exc:
        raise TranscriptError("yt-dlp gagal: %s" % str(exc)[:200])
    for name in ("json3", "vtt", "srt"):
        for found in sorted(outdir.glob("*." + name)):
            snippets = _parse_subtitle_file(found, name)
            if len(snippets) >= 3:
                return {"snippets": snippets, "language": found.stem.split(".")[-1], "source": "yt-dlp"}
    raise TranscriptError("yt-dlp tidak menemukan subtitle")


def _parse_subtitle_file(path, kind):
    text = path.read_text(encoding="utf-8", errors="ignore")
    snippets = []
    if kind == "json3":
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []
        for event in data.get("events") or []:
            segs = event.get("segs") or []
            joined = _clean_text("".join(s.get("utf8", "") for s in segs))
            if joined:
                snippets.append({"start": float(event.get("tStartMs", 0) / 1000), "duration": float(event.get("dDurationMs", 0) / 1000), "text": joined})
        return snippets
    block_pattern = re.compile(r"(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}\s*-->\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}")
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not any(block_pattern.match(line) for line in lines):
            continue
        index = next(i for i, line in enumerate(lines) if block_pattern.match(line))
        start_raw = lines[index].split("-->")[0].strip()
        start = _ts_to_seconds(start_raw)
        body = " ".join(l for l in lines[index + 1:] if not l.startswith("["))
        cleaned = _clean_text(body)
        if cleaned:
            snippets.append({"start": start, "duration": 2.0, "text": cleaned})
    return _dedupe(snippets)


def _ts_to_seconds(value):
    parts = value.replace(",", ".").split(":")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def _dedupe(snippets):
    result = []
    previous = None
    for item in snippets:
        if previous is not None and item["text"] == previous["text"]:
            previous["duration"] += 1.0
            continue
        result.append(item)
        previous = item
    return result


def _download_audio(video_id, dest_dir):
    import yt_dlp

    dest_dir = Path(dest_dir)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "user_agent": config.USER_AGENT,
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "audio.%(ext)s"),
        "retries": 3,
    }
    proxy = settings_store.proxy()
    if proxy:
        opts["proxy"] = proxy
    cookies = settings_store.cookies_file()
    if cookies:
        opts["cookiefile"] = cookies
    last_error = None
    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([video_id if str(video_id).startswith("https://") else utils_text.watch_url(video_id)])
            break
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(4 * (attempt + 1))
    else:
        raise TranscriptError("deepgram: audio gagal diunduh, %s" % str(last_error)[:160])
    for item in sorted(dest_dir.glob("audio.*")):
        if item.stat().st_size > 20000:
            return item
    return None


def _from_deepgram(video_id):
    key = settings_store.deepgram_key()
    if not key:
        raise TranscriptError("deepgram: kunci belum diisi")
    outdir = Path(tempfile.mkdtemp(prefix="dg_"))
    try:
        audio = _download_audio(video_id, outdir)
        if not audio:
            raise TranscriptError("deepgram: audio tidak ditemukan")
        payload = audio.read_bytes()
    except TranscriptError:
        shutil.rmtree(outdir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(outdir, ignore_errors=True)
        raise TranscriptError("deepgram: audio gagal diunduh, %s" % str(exc)[:160])
    shutil.rmtree(outdir, ignore_errors=True)
    params = {
        "model": config.DEEPGRAM_MODEL,
        "detect_language": "true",
        "smart_format": "true",
        "punctuate": "true",
        "utterances": "true",
    }
    try:
        resp = requests.post(
            "https://api.deepgram.com/v1/listen",
            params=params,
            data=payload,
            headers={"Authorization": "Token " + key, "Content-Type": "audio/*"},
            timeout=config.DEEPGRAM_TIMEOUT,
        )
    except Exception as exc:
        raise TranscriptError("deepgram: %s" % str(exc)[:160])
    if resp.status_code != 200:
        raise TranscriptError("deepgram: HTTP %s %s" % (resp.status_code, resp.text[:160]))
    try:
        results = resp.json().get("results") or {}
    except (json.JSONDecodeError, ValueError):
        raise TranscriptError("deepgram: jawaban bukan JSON")
    snippets = []
    for item in results.get("utterances") or []:
        text = _clean_text(item.get("transcript") or "")
        if not text:
            continue
        start = float(item.get("start") or 0.0)
        end = float(item.get("end") or start)
        snippets.append({"start": start, "duration": max(0.5, end - start), "text": text})
    channels = results.get("channels") or []
    if not snippets and channels:
        alt = (channels[0].get("alternatives") or [{}])[0]
        text = _clean_text(alt.get("transcript") or "")
        if text:
            snippets = [{"start": 0.0, "duration": 0.0, "text": text}]
    if not snippets:
        raise TranscriptError("deepgram: hasil kosong")
    language = (channels[0].get("detected_language") if channels else "") or config.TRANSCRIPT_LANGUAGES[0]
    return {"snippets": snippets, "language": language, "source": "deepgram"}


def fetch(video_id, duration=None):
    errors = []
    sparse = None
    for func in (_from_api, _from_ytdlp, _from_deepgram):
        try:
            data = func(video_id)
            if data and data.get("snippets"):
                data["snippets"] = _dedupe(data["snippets"])
                if duration and not quality(data["snippets"], duration)["adequate"]:
                    if sparse is None or len(as_plain_text(data["snippets"])) > len(as_plain_text(sparse["snippets"])):
                        sparse = data
                    continue
                return data
        except TranscriptError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append("%s: %s" % (func.__name__, str(exc)[:160]))
    if sparse:
        return sparse
    raise TranscriptError(" | ".join(errors) or "transkrip tidak tersedia")


def as_paragraphs(snippets, max_chars=900):
    paragraphs = []
    buffer = []
    length = 0
    for item in snippets:
        text = item["text"]
        if not text:
            continue
        if text[0].isupper() and length > max_chars * 0.5:
            paragraphs.append(buffer)
            buffer = [item]
            length = len(text)
            continue
        buffer.append(item)
        length += len(text) + 1
        if length >= max_chars:
            paragraphs.append(buffer)
            buffer = []
            length = 0
    if buffer:
        paragraphs.append(buffer)
    out = []
    for group in paragraphs:
        out.append({"start": group[0]["start"], "text": _tidy(" ".join(item["text"] for item in group))})
    return out


def as_plain_text(snippets):
    return _tidy(" ".join(item["text"] for item in snippets))


def quality(snippets, duration):
    """Reject noise and sparse/repeated captions, including 'halo' in a long clip."""
    cleaned, intervals = [], []
    for item in snippets:
        text = re.sub(r"\[[^\]]*\]|\([^)]*\)|[♪♫]", " ", item.get("text") or "")
        text = re.sub(r"\b(music|musik|applause|tepuk tangan|silence|hening|instrumental)\b", " ", text, flags=re.I)
        words = re.findall(r"[^\W\d_]+", text.lower(), re.UNICODE)
        cleaned.extend(words)
        if words:
            start = max(0, float(item.get("start") or 0))
            intervals.append((start, start + max(0, float(item.get("duration") or 0))))
    duration = max(1, float(duration or 1))
    covered, end = 0, 0
    for start, stop in sorted(intervals):
        stop = min(duration, stop)
        covered += max(0, stop - max(start, end))
        end = max(end, stop)
    words, unique = len(cleaned), len(set(cleaned))
    # At least five words for short clips; longer clips need proportional context.
    required = max(5, min(100, int(duration / 6)))
    enough = words >= required and unique >= min(12, required) and (
        duration <= 30 or covered / duration >= 0.08 or words / duration >= 0.35)
    return {"adequate": enough, "words": words, "unique_words": unique,
            "coverage": round(covered / duration, 3), "reason": "memadai" if enough else "kosong, noise, repetitif, atau terlalu sedikit dibanding durasi"}


def fetch_media(url):
    """Instagram has no YouTube subtitle API; use configured speech transcription."""
    return _from_deepgram(url)


def _tidy(text):
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b(?:>>)\s*", "", text)
    return text.strip()


def timed_lines(snippets, keyword):
    keyword = _clean_text(keyword).lower()
    if not keyword:
        return []
    hits = []
    for item in snippets:
        if keyword in item["text"].lower():
            hits.append((item["start"], item["text"]))
    return hits[:20]


def language_hint(video_info, snippets):
    sample = " ".join(item["text"] for item in snippets[:40]).lower()
    if re.search(r"\b(yang|ini|itu|dengan|untuk|dari|kita|saya|anda|gimana|banget)\b", sample):
        return "id"
    return "en"
