import html
import re
import threading
import time
from pathlib import Path

import requests

import config
import drafts
import wxr_builder


class WordPressError(RuntimeError):
    pass


NONCE_RE = re.compile(r"[0-9a-f]{10}")
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
CLIENT_TTL = 1200
_clients = {}
_clients_lock = threading.Lock()


class WPClient:
    def __init__(self, base, user, password):
        self.base = (base or "").strip().rstrip("/")
        self.user = (user or "").strip()
        self.password = (password or "").strip()
        if not self.base:
            raise WordPressError("Alamat WordPress kosong.")
        if not self.user or not self.password:
            raise WordPressError("User atau password WordPress kosong.")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self.nonce = None
        self.me = None
        self.lock = threading.RLock()
        self._login()

    def _login(self):
        self.session.get(self.base + "/", timeout=config.REQUEST_TIMEOUT)
        resp = self.session.post(
            self.base + "/wp-login.php",
            data={
                "log": self.user,
                "pwd": self.password,
                "wp-submit": "Log In",
                "redirect_to": self.base + "/wp-admin/",
                "testcookie": "1",
            },
            timeout=config.REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if not any("logged_in" in c.name for c in self.session.cookies):
            if resp.status_code == 429:
                raise WordPressError("Login dibatasi sementara (429). Tunggu beberapa menit lalu coba lagi.")
            raise WordPressError("Login WordPress ditolak. Cek user dan password.")
        self._refresh_nonce()

    def _refresh_nonce(self):
        last = None
        for _ in range(4):
            resp = self.session.get(
                self.base + "/wp-admin/admin-ajax.php",
                params={"action": "rest-nonce"},
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                timeout=config.REQUEST_TIMEOUT,
            )
            value = (resp.text or "").strip()
            if resp.status_code == 200 and NONCE_RE.fullmatch(value):
                self.nonce = value
                return
            last = "HTTP %d: %s" % (resp.status_code, value[:60])
            time.sleep(0.5)
        raise WordPressError("Gagal ambil nonce REST (%s)." % (last or "?"))

    def api(self, method, path, retry=True, **kwargs):
        with self.lock:
            if self.nonce is None:
                self._refresh_nonce()
            kwargs.setdefault("timeout", config.REQUEST_TIMEOUT * 2)
            headers = dict(kwargs.pop("headers", {}) or {})
            headers["X-WP-Nonce"] = self.nonce
            resp = self.session.request(method, self.base + "/wp-json/wp/v2/" + path.lstrip("/"), headers=headers, **kwargs)
            if resp.status_code in (401, 403) and retry:
                try:
                    code = resp.json().get("code", "")
                except ValueError:
                    code = ""
                if "logged_in" in code or "nonce" in code or resp.status_code == 401:
                    self._login()
                    return self.api(method, path, retry=False, headers=headers, **kwargs)
            return resp

    def whoami(self):
        if self.me:
            return self.me
        resp = self.api("GET", "users/me")
        if resp.status_code != 200:
            raise WordPressError("users/me gagal (HTTP %d): %s" % (resp.status_code, resp.text[:160]))
        self.me = resp.json()
        return self.me

    def upload_media(self, image_path, title, caption, alt, filename):
        data = {
            "title": (title or filename)[:180],
            "caption": caption or "",
            "alt_text": (alt or "")[:180],
            "description": caption or "",
        }
        files = {"file": (filename, Path(image_path).read_bytes(), "image/jpeg")}
        resp = self.api("POST", "media", files=files, data=data)
        if resp.status_code not in (200, 201):
            raise WordPressError("upload gambar gagal (HTTP %d): %s" % (resp.status_code, resp.text[:200]))
        payload = resp.json()
        return {"id": payload["id"], "url": payload.get("source_url")}

    def update_media(self, media_id, caption, alt):
        self.api("POST", "media/%d" % int(media_id), json={"caption": caption or "", "alt_text": (alt or "")[:180]})

    def find_term(self, taxonomy, name):
        resp = self.api("GET", taxonomy, params={"search": name, "per_page": 50})
        if resp.status_code != 200:
            return None
        lowered = (name or "").strip().lower()
        for item in resp.json():
            if html.unescape(item.get("name") or "").strip().lower() == lowered:
                return item["id"]
        return None

    def create_term(self, taxonomy, name):
        resp = self.api("POST", taxonomy, json={"name": name})
        if resp.status_code in (200, 201):
            return resp.json().get("id")
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if data.get("code") == "term_exists":
            return (data.get("data") or {}).get("term_id") or self.find_term(taxonomy, name)
        return None

    def resolve_category(self, name):
        found = self.find_term("categories", name)
        if found:
            return found
        created = self.create_term("categories", name)
        if not created:
            raise WordPressError("kategori '%s' gagal dibuat." % name)
        return created

    def resolve_tags(self, names):
        ids = []
        for name in names[:8]:
            found = self.find_term("tags", name) or self.create_term("tags", name)
            if found:
                ids.append(found)
        return ids

    def create_post(self, payload):
        resp = self.api("POST", "posts", json=payload)
        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 403:
            raise WordPressError("Akun tidak punya hak bikin post (403). Pakai user dengan role Editor atau Admin.")
        raise WordPressError("gagal bikin post (HTTP %d): %s" % (resp.status_code, resp.text[:260]))

    def update_post(self, post_id, payload):
        resp = self.api("POST", "posts/%d" % int(post_id), json=payload)
        if resp.status_code in (200, 201):
            return resp.json()
        raise WordPressError("gagal update post %s (HTTP %d): %s" % (post_id, resp.status_code, resp.text[:200]))

    def get_post(self, post_id):
        resp = self.api("GET", "posts/%d" % int(post_id), params={"context": "edit"})
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        raise WordPressError("gagal baca post %s (HTTP %d)" % (post_id, resp.status_code))


INPUT_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
ATTR_RE = re.compile(r"""(\w[\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _inputs(fragment):
    found = []
    for tag in INPUT_RE.findall(fragment):
        attrs = {m.group(1).lower(): html.unescape(m.group(2) if m.group(2) is not None else m.group(3)) for m in ATTR_RE.finditer(tag)}
        if attrs.get("name"):
            found.append((attrs["name"], attrs.get("value", "")))
    return found


def _form(page, class_name):
    start = page.find('<form class="%s"' % class_name)
    if start < 0:
        return ""
    end = page.find("</form>", start)
    return page[start:end]


def set_yoast(client, post_id, fields):
    page = client.session.get(
        client.base + "/wp-admin/post.php", params={"post": int(post_id), "action": "edit"}, timeout=config.REQUEST_TIMEOUT * 2
    ).text
    match = re.search(r'_wpMetaBoxUrl\s*=\s*"([^"]+)"', page)
    if not match:
        raise WordPressError("form SEO tidak ditemukan di editor")
    url = html.unescape(match.group(1).replace("\\/", "/"))
    data = {}
    for name, value in _inputs(_form(page, "metabox-base-form")):
        data.setdefault(name, value)
    for class_name in ("metabox-location-side", "metabox-location-normal", "metabox-location-advanced"):
        for name, value in _inputs(_form(page, class_name)):
            if name.startswith("yoast") and name not in data:
                data[name] = value
    if "yoast_free_metabox_nonce" not in data:
        raise WordPressError("nonce SEO tidak ditemukan")
    data["post_ID"] = str(int(post_id))
    data["action"] = "editpost"
    for key, value in fields.items():
        if value:
            data["yoast_wpseo_%s" % key] = value
    resp = client.session.post(url, data=data, timeout=config.REQUEST_TIMEOUT * 2)
    if resp.status_code not in (200, 302):
        raise WordPressError("simpan SEO gagal (HTTP %d)" % resp.status_code)
    return True


def read_yoast(client, post_id):
    page = client.session.get(
        client.base + "/wp-admin/post.php", params={"post": int(post_id), "action": "edit"}, timeout=config.REQUEST_TIMEOUT * 2
    ).text
    values = {}
    for class_name in ("metabox-location-side", "metabox-location-normal", "metabox-location-advanced"):
        for name, value in _inputs(_form(page, class_name)):
            if name.startswith("yoast_wpseo_"):
                values.setdefault(name[len("yoast_wpseo_"):], value)
    return values


def client_for(values):
    key = (values.get("wp_url"), values.get("wp_user"), values.get("wp_app_password"))
    with _clients_lock:
        cached = _clients.get(key)
        if cached and time.time() - cached[1] < CLIENT_TTL:
            _clients[key] = (cached[0], time.time())
            return cached[0]
    fresh = WPClient(*key)
    with _clients_lock:
        _clients[key] = (fresh, time.time())
    return fresh


def ready(values):
    return bool(values.get("wp_url") and values.get("wp_user") and values.get("wp_app_password"))


def test_connection(values):
    with _clients_lock:
        _clients.clear()
    client = client_for(values)
    me = client.whoami()
    return {"id": me.get("id"), "name": me.get("name"), "roles": me.get("roles") or []}


def _links(client, post):
    post_id = post["id"]
    return {
        "admin_edit": "%s/wp-admin/post.php?post=%s&action=edit" % (client.base, post_id),
        "preview": "%s/?p=%s&preview=true" % (client.base, post_id),
        "link": post.get("link") or "%s/?p=%s" % (client.base, post_id),
    }


def _say(on_progress, message):
    if on_progress:
        try:
            on_progress(message)
        except Exception:
            pass


def push(draft, values, on_progress=None, status=None):
    client = client_for(values)
    me = client.whoami()
    article = draft["article"]
    wp = draft.get("wp") or {}

    images = wxr_builder.ordered_images(draft)
    pending = [img for img in images if not img.get("media_id")]
    for count, img in enumerate(pending):
        path = img.get("path")
        if not path or not Path(path).exists():
            continue
        _say(on_progress, "Upload gambar %d dari %d..." % (count + 1, len(pending)))
        position = images.index(img)
        uploaded = client.upload_media(
            path,
            (img.get("caption") or img.get("alt") or article["title"])[:180],
            img.get("caption") or "",
            img.get("alt") or "",
            wxr_builder.media_filename(draft, img, position),
        )
        img["media_id"] = uploaded["id"]
        img["url"] = uploaded["url"]

    media = {}
    for img in images:
        if img.get("media_id") and img.get("url"):
            media[img["key"]] = {"id": img["media_id"], "src": img["url"], "alt": img.get("alt"), "caption": img.get("caption")}
    content = wxr_builder.render_content(draft, media)

    _say(on_progress, "Siapkan kategori dan tag...")
    category_id = client.resolve_category(article.get("category") or config.WP_DEFAULT_CATEGORY)
    tag_ids = client.resolve_tags(article.get("tags") or [])

    payload = {
        "title": article["title"],
        "content": content,
        "excerpt": article.get("excerpt") or "",
        "categories": [category_id],
        "tags": tag_ids,
    }
    featured = next((img for img in images if img.get("role") == "featured" and img.get("media_id")), None)
    if featured:
        payload["featured_media"] = featured["media_id"]

    video_id = (draft.get("source") or {}).get("video_id")
    if not wp.get("post_id") and video_id:
        known = drafts.find_post_for_video(video_id, client.base)
        if known:
            candidate = client.get_post(known)
            if candidate is not None and candidate.get("status") in ("draft", "pending", "private", "publish"):
                wp["post_id"] = known
                wp["status"] = candidate.get("status")

    current_status = wp.get("status")
    if not current_status or current_status in ("draft", "pending", "auto-draft"):
        payload["slug"] = wxr_builder.slug_for(draft)

    if wp.get("post_id"):
        _say(on_progress, "Perbarui artikel di WordPress...")
        if status:
            payload["status"] = status
        post = client.update_post(wp["post_id"], payload)
    else:
        _say(on_progress, "Kirim artikel ke WordPress...")
        payload["status"] = status or values.get("wp_status") or "draft"
        payload["author"] = me["id"]
        post = client.create_post(payload)

    if featured:
        try:
            client.update_media(featured["media_id"], featured.get("caption"), featured.get("alt"))
        except Exception:
            pass

    _say(on_progress, "Isi pengaturan SEO...")
    seo_fields = {
        "focuskw": article.get("focus_keyword"),
        "metadesc": article.get("excerpt"),
        "title": "%s %%%%sep%%%% %%%%sitename%%%%" % article["seo_title"] if article.get("seo_title") else "",
        "primary_category_term": str(category_id),
    }
    try:
        set_yoast(client, post["id"], seo_fields)
        wp["seo"] = "ok"
        post = client.get_post(post["id"]) or post
    except Exception as exc:
        wp["seo"] = str(exc)[:200]

    wp.update(_links(client, post))
    wp.update(
        {
            "post_id": post["id"],
            "status": post.get("status"),
            "slug": post.get("slug"),
            "modified": post.get("modified_gmt"),
            "words": wxr_builder.word_count(content),
            "site": client.base,
        }
    )
    draft["wp"] = wp
    return wp


def set_status(draft, values, status):
    client = client_for(values)
    wp = draft.get("wp") or {}
    if not wp.get("post_id"):
        raise WordPressError("Artikel ini belum ada di WordPress.")
    post = client.update_post(wp["post_id"], {"status": status})
    wp.update(_links(client, post))
    wp.update({"status": post.get("status"), "modified": post.get("modified_gmt"), "slug": post.get("slug")})
    draft["wp"] = wp
    return wp


def changed_on_site(draft, values):
    wp = draft.get("wp") or {}
    if not wp.get("post_id") or not wp.get("modified"):
        return False
    post = client_for(values).get_post(wp["post_id"])
    if post is None:
        draft["wp"] = {}
        return False
    return post.get("modified_gmt") != wp.get("modified")
