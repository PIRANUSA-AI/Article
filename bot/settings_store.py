import json
import re
from pathlib import Path

import config

SETTINGS_FILE = config.DATA_DIR / "settings.json"
DEFAULTS = {
    "languages": None,
    "proxy": "",
    "brief": "",
    "frame": None,
    "public_base": None,
    "allow_all": False,
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
    return get("proxy", "")


def normalize_langs(text):
    codes = re.findall(r"[a-zA-Z]{2}(?:[-_][a-zA-Z]{2,4})?", text or "")
    seen, out = set(), []
    for code in codes:
        code = code.lower().replace("_", "-")
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out[:6]
