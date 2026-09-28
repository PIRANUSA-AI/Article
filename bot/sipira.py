import logging
import secrets

import requests

import config
import settings_store

log = logging.getLogger("piranusa.bot")


class SipiraError(RuntimeError):
    pass


def _base():
    return str(config.SIPIRA_BASE or "").rstrip("/")


def _headers():
    key = settings_store.sipira_key()
    if not key:
        raise SipiraError("kunci SIPIRA belum diisi")
    return {"x-api-key": key, "Content-Type": "application/json"}


def _payload(resp):
    try:
        return resp.json().get("payload")
    except (ValueError, AttributeError):
        raise SipiraError("jawaban SIPIRA bukan JSON")


def _campaign(slug):
    slug = str(slug or "").strip().lower()
    resp = requests.get(_base() + "/public/campaigns", headers=_headers(), timeout=config.SIPIRA_TIMEOUT)
    if resp.status_code != 200:
        raise SipiraError("daftar campaign gagal, HTTP %s" % resp.status_code)
    for item in _payload(resp) or []:
        if str(item.get("slug") or "").strip().lower() == slug:
            return item
    raise SipiraError("campaign %s tidak ditemukan" % slug)


def _find_link(campaign_id, slug):
    slug = str(slug or "").strip().lower()
    resp = requests.get(
        _base() + "/public/campaigns/%s/links" % campaign_id,
        headers=_headers(),
        timeout=config.SIPIRA_TIMEOUT,
    )
    if resp.status_code != 200:
        return None
    for item in _payload(resp) or []:
        if str(item.get("slug") or "").strip().lower() == slug:
            return item
    return None


def new_code(length=None):
    size = max(4, int(length or config.SIPIRA_CODE_LENGTH))
    return "".join(secrets.choice(config.SIPIRA_CODE_ALPHABET) for _ in range(size))


def _post_link(campaign_id, code, label):
    body = {
        "label": (str(label or "").strip() or code)[:160],
        "slug": code,
        "default_text": config.SIPIRA_TEXT[:2000],
    }
    return requests.post(
        _base() + "/public/campaigns/%s/links" % campaign_id,
        headers=_headers(),
        json=body,
        timeout=config.SIPIRA_TIMEOUT,
    )


def make_button(label, code=None):
    campaign = _campaign(settings_store.sipira_campaign())
    campaign_id = campaign["id"]
    if code:
        found = _find_link(campaign_id, code)
        if found and found.get("short_url"):
            return {"url": found["short_url"], "code": code}
    last = None
    for _ in range(4):
        candidate = new_code()
        resp = _post_link(campaign_id, candidate, label)
        if resp.status_code == 201:
            payload = _payload(resp) or {}
            url = payload.get("short_url")
            if url:
                return {"url": url, "code": payload.get("slug") or candidate}
            raise SipiraError("sub url dibuat tapi short_url kosong")
        last = "HTTP %s %s" % (resp.status_code, (resp.text or "")[:150])
        if resp.status_code not in (400, 409):
            break
    raise SipiraError("bikin sub url gagal, %s" % last)


def fallback_url():
    try:
        return _campaign(settings_store.sipira_campaign()).get("short_url") or ""
    except Exception:
        return ""


def cta_link(label, code=None):
    try:
        return make_button(label, code)
    except Exception as exc:
        log.warning("sipira gagal, pakai cadangan: %s", str(exc)[:200])
        return {"url": fallback_url(), "code": None}
