import html
import json
import re
import time
from urllib.parse import urlparse

import requests

import config

CACHE_FILE = config.CACHE_DIR / "site_posts.json"
CACHE_TTL = 1800
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "untuk", "dengan", "ini", "itu", "cara", "pakai", "bisa", "lebih",
    "dalam", "pada", "atau", "jadi", "tanpa", "the", "and", "for", "how", "kamu", "anda",
}


def site_host():
    return (urlparse(config.SITE_LINK).netloc or "").replace("www.", "")


def is_internal(url):
    host = (urlparse(url).netloc or "").replace("www.", "")
    return bool(host) and host == site_host()


def _fetch():
    posts = []
    for page in (1, 2):
        resp = requests.get(
            config.SITE_LINK.rstrip("/") + "/wp-json/wp/v2/posts",
            params={"per_page": 50, "page": page, "_fields": "id,title,link,date"},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            break
        batch = resp.json()
        posts += [
            {"title": html.unescape(re.sub(r"<[^>]+>", "", p["title"]["rendered"])).strip(), "url": p["link"]}
            for p in batch
            if p.get("link") and p.get("title", {}).get("rendered")
        ]
        if len(batch) < 50:
            break
    return posts


def site_posts():
    if CACHE_FILE.exists() and time.time() - CACHE_FILE.stat().st_mtime < CACHE_TTL:
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    try:
        posts = _fetch()
    except Exception:
        posts = []
    if posts:
        CACHE_FILE.write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
        return posts
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except ValueError:
            return []
    return []


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in STOPWORDS}


def related(text, limit=12):
    words = _tokens(text)
    scored = []
    for post in site_posts():
        overlap = len(words & _tokens(post["title"]))
        scored.append((overlap, post))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked = [post for score, post in scored if score > 0][:limit]
    if len(picked) < 4:
        for score, post in scored:
            if post not in picked:
                picked.append(post)
            if len(picked) >= min(limit, 6):
                break
    return picked


def external_from(material, extra=()):
    urls = []
    for url in list(extra) + URL_RE.findall(material or ""):
        url = url.rstrip(".,")
        if is_internal(url) or url in urls:
            continue
        if any(bad in url for bad in ("bit.ly", "wa.me", "whatsapp", "t.me", "facebook.com/sharer")):
            continue
        urls.append(url)
    return urls[:6]


def internal_from(material):
    return [url.rstrip(".,") for url in URL_RE.findall(material or "") if is_internal(url)][:4]
