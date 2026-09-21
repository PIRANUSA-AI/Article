import logging

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


def make_button(article_slug, label):
    article_slug = str(article_slug or "").strip()[:80]
    if not article_slug:
        raise SipiraError("slug artikel kosong")
    campaign = _campaign(settings_store.sipira_campaign())
    campaign_id = campaign["id"]
    body = {
        "label": (str(label or "").strip() or article_slug)[:160],
        "slug": article_slug,
        "default_text": config.SIPIRA_TEXT[:2000],
    }
    resp = requests.post(
        _base() + "/public/campaigns/%s/links" % campaign_id,
        headers=_headers(),
        json=body,
        timeout=config.SIPIRA_TIMEOUT,
    )
    if resp.status_code == 201:
        url = (_payload(resp) or {}).get("short_url")
        if url:
            return url
        raise SipiraError("sub url dibuat tapi short_url kosong")
    if resp.status_code in (400, 409):
        found = _find_link(campaign_id, article_slug)
        if found and found.get("short_url"):
            return found["short_url"]
    raise SipiraError("bikin sub url gagal, HTTP %s %s" % (resp.status_code, (resp.text or "")[:150]))


def fallback_url():
    try:
        return _campaign(settings_store.sipira_campaign()).get("short_url") or ""
    except Exception:
        return ""


def cta_url(article_slug, label):
    try:
        return make_button(article_slug, label)
    except Exception as exc:
        log.warning("sipira gagal, pakai cadangan: %s", str(exc)[:200])
        return fallback_url()
