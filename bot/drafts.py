import copy
import datetime as dt
import json
import os
import secrets
import threading

import config

INDEX_FILE = config.DRAFTS_DIR / "messages.json"
HISTORY_LIMIT = 6
_lock = threading.RLock()


def new_id():
    return secrets.token_hex(4)


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path(draft_id):
    safe = "".join(ch for ch in str(draft_id) if ch.isalnum())
    return config.DRAFTS_DIR / ("%s.json" % safe)


def _write_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(temp, path)


def save(draft):
    with _lock:
        draft["updated"] = now()
        _write_json(_path(draft["id"]), draft)
    return draft


def load(draft_id):
    path = _path(draft_id)
    if not path.exists():
        return None
    with _lock:
        return json.loads(path.read_text(encoding="utf-8"))


def _index():
    if not INDEX_FILE.exists():
        return {}
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def remember_message(draft_id, chat_id, message_id):
    if not message_id:
        return
    with _lock:
        index = _index()
        index["%s:%s" % (chat_id, message_id)] = draft_id
        if len(index) > 4000:
            index = dict(list(index.items())[-3000:])
        _write_json(INDEX_FILE, index)


def for_message(chat_id, message_id):
    with _lock:
        return _index().get("%s:%s" % (chat_id, message_id))


def snapshot(draft, label):
    history = draft.setdefault("history", [])
    history.append({"at": now(), "label": label, "article": copy.deepcopy(draft["article"]), "images": copy.deepcopy(draft["images"])})
    del history[:-HISTORY_LIMIT]


def undo(draft):
    history = draft.get("history") or []
    if not history:
        return None
    last = history.pop()
    draft["article"] = last["article"]
    draft["images"] = last["images"]
    return last["label"]


def find_post_for_video(video_id, site):
    best = None
    for path in config.DRAFTS_DIR.glob("*.json"):
        if path.name == INDEX_FILE.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if (data.get("source") or {}).get("video_id") != video_id:
            continue
        wp = data.get("wp") or {}
        post_id = wp.get("post_id")
        if not post_id or (wp.get("site") or "") != site:
            continue
        stamp = data.get("updated") or ""
        if best is None or stamp > best[0]:
            best = (stamp, int(post_id))
    return best[1] if best else None


def latest_for(owner):
    candidates = []
    for path in config.DRAFTS_DIR.glob("*.json"):
        if path.name == INDEX_FILE.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if data.get("owner") == owner:
            candidates.append((data.get("updated") or "", data["id"]))
    if not candidates:
        return None
    return sorted(candidates)[-1][1]
