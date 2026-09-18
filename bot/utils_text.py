import hashlib
import re

URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.|m\.|music\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)
PLAIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(text):
    if not text:
        return None
    match = URL_PATTERN.search(text)
    if match:
        return match.group(1)
    cleaned = text.strip().split()[0] if text.strip() else ""
    if PLAIN_ID_PATTERN.match(cleaned):
        return cleaned
    return None


def watch_url(video_id):
    return "https://www.youtube.com/watch?v=%s" % video_id


def slugify(value, maxlen=70):
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    if not value:
        value = "artikel"
    return value[:maxlen].rstrip("-")


def short_hash(value, length=8):
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]
