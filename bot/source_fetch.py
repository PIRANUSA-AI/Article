"""Read public article and Instagram sources without treating a URL as article text."""
import ipaddress
import json
import socket
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import config
import settings_store


class SourceError(RuntimeError):
    pass


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise SourceError("URL sumber tidak valid")
    for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        if not ipaddress.ip_address(item[4][0]).is_global:
            raise SourceError("Sumber harus berupa alamat internet publik")
    return url


def download(url, dest=None, max_bytes=12_000_000):
    for _ in range(6):
        validate_url(url)
        with requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=config.REQUEST_TIMEOUT,
                          stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > max_bytes:
                    raise SourceError("Ukuran sumber melebihi batas unduhan")
                chunks.append(chunk)
            body = b"".join(chunks)
            if dest:
                Path(dest).write_bytes(body)
            return body, response.encoding or "utf-8", url
    raise SourceError("Redirect sumber terlalu banyak")


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.blocks, self.title = {}, [], []
        self.skip = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "nav", "footer", "header", "aside", "noscript"):
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            self.meta[attrs.get("property") or attrs.get("name")] = attrs.get("content", "")
        if not self.skip and tag in ("p", "h1", "h2", "h3", "li", "article", "br"):
            self.blocks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header", "aside", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self.in_title = False
        if not self.skip and tag in ("p", "h1", "h2", "h3", "li"):
            self.blocks.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if not self.skip:
            self.blocks.append(data)


def article(url):
    raw, encoding, final_url = download(url, max_bytes=4_000_000)
    from charset_normalizer import from_bytes
    detected = from_bytes(raw).best()
    html_text = str(detected) if detected is not None else raw.decode(encoding, errors="replace")
    page = Page()
    page.feed(html_text)
    # Trafilatura isolates the article body; the parser also supplies metadata.
    import trafilatura
    body = trafilatura.extract(html_text, url=final_url,
                               include_comments=False, include_tables=True)
    if not body or len(body.strip()) < 200:
        raise SourceError("Isi artikel tidak terbaca. Tempel teks artikelnya; halaman mungkin terkunci atau memerlukan login.")
    return {"type": "article", "url": final_url,
            "title": page.meta.get("og:title") or " ".join(page.title), "text": body}


def is_instagram(url):
    return (urlparse(url).hostname or "").lower() in ("instagram.com", "www.instagram.com", "m.instagram.com")


def instagram(url, work_dir):
    """yt-dlp uses the configured cookies for stories requiring a permitted login."""
    import yt_dlp
    import video_source

    validate_url(url)
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 30,
            "ignore_no_formats_error": True, "noplaylist": True}
    cookies = settings_store.cookies_file()
    if cookies:
        opts["cookiefile"] = cookies
    if settings_store.proxy():
        opts["proxy"] = settings_store.proxy()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise SourceError("Instagram belum bisa dibaca. Untuk story, gunakan link story spesifik yang masih aktif dan cookies akun yang memiliki akses. "
                          "Postingan privat atau kedaluwarsa perlu dikirim sebagai foto/video. (%s)" % type(exc).__name__) from exc
    if not isinstance(info, dict):
        raise SourceError("Media Instagram tidak ditemukan atau sudah tidak tersedia")
    items = list(info.get("entries") or [info])
    if len(items) > 12:
        raise SourceError("Satu kiriman dibatasi 12 media. Kirim link media yang lebih spesifik.")
    texts, images, videos = [info.get("description") or ""], [], []
    for index, item in enumerate(items):
        if not item:
            continue
        texts.append(item.get("description") or item.get("title") or "")
        folder = Path(work_dir) / ("instagram_%02d" % index)
        folder.mkdir(parents=True, exist_ok=True)
        stream = video_source._best_direct_url(item)
        if stream or item.get("vcodec") not in (None, "none"):
            videos.append({"video_id": str(item.get("id") or index), "url": item.get("webpage_url") or url,
                           "stream_url": stream or item.get("url"), "duration": item.get("duration") or 0,
                           "download_url": stream or item.get("url"),
                           "title": item.get("title") or "Instagram", "description": item.get("description") or "",
                           "channel": item.get("uploader") or "", "work_dir": str(folder)})
        else:
            image_url = item.get("url") or item.get("thumbnail")
            if not image_url:
                thumbs = item.get("thumbnails") or []
                image_url = thumbs[-1].get("url") if thumbs else None
            if image_url:
                path = folder / "photo.jpg"
                download(image_url, path)
                images.append(str(path))
    if not images and not videos:
        raise SourceError("Media Instagram tidak terbaca. Kirim foto/video sumber langsung.")
    return {"type": "instagram", "url": url, "title": info.get("title") or "Instagram",
            "text": "\n\n".join(dict.fromkeys(texts)), "images": images, "videos": videos}
