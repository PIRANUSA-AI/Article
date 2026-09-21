import json
import re
import secrets
from pathlib import Path

import config

SETTINGS_FILE = config.DATA_DIR / "settings.json"
KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
KEY_LENGTH = 6
DEFAULTS = {
    "languages": None,
    "proxy": "",
    "brief": "",
    "frame": None,
    "public_base": None,
    "allow_all": False,
    "app_key": "",
    "unlocked_users": [],
    "deepgram_key": "",
    "sipira_key": "",
    "sipira_campaign": "",
    "publish_mode": "push",
    "wp_url": config.WP_URL,
    "wp_user": config.WP_USER,
    "wp_app_password": config.WP_APP_PASSWORD,
    "wp_status": config.WP_STATUS,
}


def _read():
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            data = {}
    else:
        data = {}
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def _write(values):
    SETTINGS_FILE.write_text(json.dumps(values, ensure_ascii=False, indent=1), encoding="utf-8")


def get(key, default=None):
    values = _read()
    value = values.get(key)
    if value in (None, "", []) and default is not None:
        return default
    if value is None:
        return DEFAULTS.get(key)
    return value


def set_value(key, value):
    values = _read()
    values[key] = value
    _write(values)


def all_values():
    return _read()


def languages():
    return get("languages") or config.TRANSCRIPT_LANGUAGES


def proxy():
    return get("proxy", "") or config.YTDLP_PROXY


def cookies_file():
    path = Path(config.YTDLP_COOKIES)
    return str(path) if path.is_file() else ""


def deepgram_key():
    return str(get("deepgram_key", "") or "").strip() or config.DEEPGRAM_API_KEY


def sipira_key():
    return str(get("sipira_key", "") or "").strip() or config.SIPIRA_API


def sipira_campaign():
    return str(get("sipira_campaign", "") or "").strip() or config.SIPIRA_CAMPAIGN


def _make_key():
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_LENGTH))


def app_key():
    value = str(get("app_key", "") or "").strip().upper()
    if len(value) == KEY_LENGTH:
        return value
    value = _make_key()
    set_value("app_key", value)
    return value


def rotate_app_key():
    value = _make_key()
    set_value("app_key", value)
    set_value("unlocked_users", [])
    return value


def unlocked_users():
    raw = get("unlocked_users", []) or []
    out = []
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def is_unlocked(user_id):
    try:
        return int(user_id) in unlocked_users()
    except (TypeError, ValueError):
        return False


def unlock(user_id):
    values = unlocked_users()
    user_id = int(user_id)
    if user_id not in values:
        values.append(user_id)
        set_value("unlocked_users", values)
    return values


def lock(user_id):
    values = [item for item in unlocked_users() if item != int(user_id)]
    set_value("unlocked_users", values)
    return values


def normalize_langs(text):
    codes = re.findall(r"[a-zA-Z]{2}(?:[-_][a-zA-Z]{2,4})?", text or "")
    seen, out = set(), []
    for code in codes:
        code = code.lower().replace("_", "-")
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out[:6]
