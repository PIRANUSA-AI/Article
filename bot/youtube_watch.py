import datetime as dt
import json
import os
import threading

import config
import drafts
import settings_store
import testimonial
import utils_text
import wordpress_push

STATE_FILE = config.DATA_DIR / "youtube_watch.json"
POST_STATUSES = "publish,draft,pending,private,future"
_lock = threading.RLock()


def now_wib():
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7)


def _read():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _write(state):
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, STATE_FILE)


def channel_videos():
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "nocheckcertificate": True,
        "user_agent": config.USER_AGENT,
    }
    proxy = settings_store.proxy()
    if proxy:
        opts["proxy"] = proxy
    cookies = settings_store.cookies_file()
    if cookies:
        opts["cookiefile"] = cookies
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(config.YOUTUBE_CHANNEL_URL, download=False)
    out = []
    for entry in info.get("entries") or []:
        video_id = entry.get("id")
        if video_id and utils_text.PLAIN_ID_PATTERN.match(video_id):
            out.append({"id": video_id, "title": entry.get("title") or video_id, "url": utils_text.watch_url(video_id)})
    return out


def _post_videos(client):
    found = set()
    page_no = 1
    while True:
        resp = client.api("GET", "posts", params={"per_page": 100, "page": page_no, "status": POST_STATUSES, "context": "edit", "_fields": "id,content"})
        if resp.status_code != 200:
            break
        items = resp.json()
        for item in items:
            raw = (item.get("content") or {}).get("raw") or ""
            found.update(m.group(1) for m in utils_text.URL_PATTERN.finditer(raw))
        if len(items) < 100:
            break
        page_no += 1
    return found


def _draft_videos():
    found = set()
    for path in config.DRAFTS_DIR.glob("*.json"):
        if path.name == drafts.INDEX_FILE.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        video_id = (data.get("source") or {}).get("video_id")
        if video_id:
            found.add(video_id)
    return found


def covered():
    values = settings_store.all_values()
    found = _draft_videos()
    if wordpress_push.ready(values):
        client = wordpress_push.client_for(values)
        found |= _post_videos(client)
        found |= set(testimonial.known_videos(client, refresh=True))
    return found


def report():
    videos = channel_videos()
    done = covered()
    today = now_wib().strftime("%Y-%m-%d")
    with _lock:
        state = _read()
        first_seen = state.setdefault("first_seen", {})
        baseline = not first_seen
        for video in videos:
            first_seen.setdefault(video["id"], "baseline" if baseline else today)
        skipped = set(state.get("skipped") or [])
        _write(state)
    pending = [v for v in videos if v["id"] not in done and v["id"] not in skipped]
    fresh = [v for v in pending if first_seen.get(v["id"]) != "baseline"]
    backlog = [v for v in pending if first_seen.get(v["id"]) == "baseline"]
    return {"new": fresh, "backlog": backlog, "total": len(videos), "covered": sum(1 for v in videos if v["id"] in done)}


def skip(video_id):
    with _lock:
        state = _read()
        skipped = state.setdefault("skipped", [])
        if video_id not in skipped:
            skipped.append(video_id)
        _write(state)


def due(moment=None):
    moment = moment or now_wib()
    if moment.hour < config.REMINDER_HOUR:
        return []
    today = moment.date()
    with _lock:
        state = _read()
    kinds = []
    if moment.weekday() in config.REMINDER_BACKLOG_DAYS and state.get("last_backlog") != today.isoformat():
        kinds.append("backlog")
    last_new = state.get("last_new")
    if not last_new or (today - dt.date.fromisoformat(last_new)).days >= config.REMINDER_NEW_EVERY_DAYS:
        kinds.append("new")
    return kinds


def mark(kind, moment=None):
    moment = moment or now_wib()
    with _lock:
        state = _read()
        state["last_%s" % kind] = moment.date().isoformat()
        _write(state)
