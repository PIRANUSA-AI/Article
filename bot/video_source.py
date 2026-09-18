import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

import config
import settings_store
import utils_text


class VideoError(RuntimeError):
    pass


def _ydl():
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "user_agent": config.USER_AGENT,
    }
    proxy = settings_store.proxy()
    if proxy:
        opts["proxy"] = proxy
    cookies = settings_store.cookies_file()
    if cookies:
        opts["cookiefile"] = cookies
    return yt_dlp.YoutubeDL(opts)


def probe(video_id):
    url = utils_text.watch_url(video_id)
    try:
        with _ydl() as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise VideoError("gagal membaca metadata video: %s" % str(exc)[:300])
    duration = info.get("duration") or 0
    thumbnails = sorted(info.get("thumbnails") or [], key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=True)
    return {
        "video_id": info.get("id") or video_id,
        "url": utils_text.watch_url(info.get("id") or video_id),
        "title": info.get("title") or "",
        "channel": info.get("uploader") or info.get("channel") or info.get("uploader_id") or "",
        "duration": int(duration),
        "upload_date": info.get("upload_date") or "",
        "view_count": info.get("view_count"),
        "description": (info.get("description") or "")[:4000],
        "thumbnail_url": thumbnails[0]["url"] if thumbnails else "https://i.ytimg.com/vi/%s/maxresdefault.jpg" % video_id,
        "languages": info.get("languages") or [],
        "stream_url": _best_direct_url(info),
    }


def _best_direct_url(info):
    candidates = [
        f
        for f in (info.get("formats") or [])
        if f.get("url") and f.get("vcodec") not in (None, "none") and (f.get("protocol") or "").startswith("https") and (f.get("ext") or "").lower() in ("mp4", "webm", "mkv", "mov", "3gp")
    ]
    if not candidates:
        broad = [f for f in (info.get("formats") or []) if f.get("url") and f.get("vcodec") not in (None, "none") and (f.get("protocol") or "").startswith("https")]
        candidates = broad
    if not candidates:
        return None

    def score(fmt):
        height = fmt.get("height") or 0
        near = abs(height - 720)
        ext_rank = 0 if (fmt.get("ext") or "").lower() == "mp4" else 1
        return (near, ext_rank, -(fmt.get("tbr") or 0))

    candidates.sort(key=score)
    return candidates[0]["url"]


def download_thumbnail(video_info, dest_dir):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = video_info.get("thumbnail_url") or ""
    for candidate in [url, "https://i.ytimg.com/vi/%s/maxresdefault.jpg" % video_info["video_id"], "https://i.ytimg.com/vi/%s/hqdefault.jpg" % video_info["video_id"]]:
        if not candidate:
            continue
        try:
            resp = requests.get(candidate, timeout=config.REQUEST_TIMEOUT, headers={"User-Agent": config.USER_AGENT})
            if resp.status_code == 200 and len(resp.content) > 800:
                suffix = ".jpg"
                if "png" in (resp.headers.get("content-type") or ""):
                    suffix = ".png"
                path = dest_dir / ("thumbnail%s" % suffix)
                path.write_bytes(resp.content)
                return path
        except Exception:
            continue
    return None


def _download_source(video_info, dest_dir):
    import yt_dlp

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for existing in sorted(dest_dir.glob("source.*")):
        if existing.stat().st_size > 200000:
            return str(existing)
    cap = config.FRAME_MAX_HEIGHT
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "user_agent": config.USER_AGENT,
        "format": "bv*[height<=%d]/b[height<=%d]/bv*/b" % (cap, cap),
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "retries": 3,
    }
    proxy = settings_store.proxy()
    if proxy:
        opts["proxy"] = proxy
    cookies = settings_store.cookies_file()
    if cookies:
        opts["cookiefile"] = cookies
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([video_info.get("url") or utils_text.watch_url(video_info["video_id"])])
    except Exception:
        return None
    for made in sorted(dest_dir.glob("source.*")):
        if made.stat().st_size > 200000:
            return str(made)
    return None


def _frame_source(video_info, dest_dir):
    if settings_store.proxy():
        local = _download_source(video_info, dest_dir)
        if local:
            return local
    return video_info.get("stream_url")


def _ffmpeg_frame(source, seconds, out_path):
    cmd = [
        config.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", str(max(0, int(seconds))), "-i", source,
        "-frames:v", "1",
        "-vf", "scale=-2:%d" % config.FRAME_MAX_HEIGHT,
        "-q:v", "2",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        raise VideoError("ffmpeg tidak ditemukan di mesin ini")
    if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 4000:
        return out_path
    return None


def grab_frames(video_info, dest_dir, count=None):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    duration = max(1, int(video_info.get("duration") or 0))
    source = _frame_source(video_info, dest_dir)
    frames = []
    if not source:
        return frames
    points = _sample_points(duration, count or config.FRAME_COUNT)
    for index, point in enumerate(points):
        out_path = dest_dir / ("frame_%02d_%ds.jpg" % (index, point))
        made = _ffmpeg_frame(source, point, out_path)
        if made:
            frames.append({"path": made, "seconds": point, "label": _fmt_time(point)})
        time.sleep(0.4)
    return frames


def frame_at(video_info, seconds, dest_dir):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    seconds = max(0, int(seconds))
    source = _frame_source(video_info, dest_dir)
    if not source:
        return None
    out_path = dest_dir / ("frame_custom_%ds.jpg" % seconds)
    made = _ffmpeg_frame(source, seconds, out_path)
    if not made:
        made = _ffmpeg_frame(source, max(0, seconds - 5), out_path)
    if not made:
        return None
    return {"path": made, "seconds": seconds, "label": _fmt_time(seconds), "kind": "requested"}


def _sample_points(duration, count):
    count = max(2, int(count))
    start = max(2, int(duration * 0.08))
    end = max(start + 1, int(duration * 0.92))
    step = (end - start) / float(max(1, count - 1))
    points = [int(start + step * i) for i in range(count)]
    seen, result = set(), []
    for point in points:
        if point not in seen:
            seen.add(point)
            result.append(point)
    return result


def _fmt_time(seconds):
    seconds = int(seconds)
    return "%02d:%02d" % (seconds // 60, seconds % 60)


def _keyframe_candidates(video_info, dest_dir, stream_url):
    if not stream_url or "youtube" not in (urlparse(stream_url).netloc or ""):
        return []
    host = urlparse(stream_url).netloc
    path = urlparse(stream_url).path
    if "/videoplayback" not in path:
        return []
    try:
        resp = requests.get(
            "https://%s/youtube/v1/keyframe_bounds" % host,
            params={"id": _base64_segment(video_info["video_id"])},
            timeout=20,
            headers={"User-Agent": config.USER_AGENT},
        )
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError):
        return []
    points = []
    for clip in payload.get("clips") or []:
        for mark in clip.get("marks") or []:
            if isinstance(mark, dict) and "t" in mark:
                points.append(int(mark["t"]))
    return points[:40]


def _base64_segment(video_id):
    import base64

    return base64.urlsafe_b64encode(video_id.encode("utf-8")).decode("ascii").rstrip("=")


def parse_timestamp(text):
    text = (text or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return int(text)
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})", text)
    if match:
        h, m, s = match.groups()
        return int(h or 0) * 3600 + int(m) * 60 + int(s)
    match = re.fullmatch(r"(\d+):(\d{1,2})", text)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    return None
