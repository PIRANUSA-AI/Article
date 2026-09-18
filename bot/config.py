import os
from pathlib import Path


def _load_dotenv():
    here = Path(__file__).resolve().parent
    for candidate in (here / ".env", here.parent / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv()


def _env(key, default):
    value = os.getenv(key)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_int(key, default):
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_list(key, default):
    raw = _env(key, "")
    if not raw:
        return list(default)
    return [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]


BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR.parent
DATA_DIR = Path(_env("BOT_DATA_DIR", str(WORKSPACE_DIR / "data")))
MEDIA_DIR = DATA_DIR / "media"
JOBS_DIR = DATA_DIR / "jobs"
CACHE_DIR = DATA_DIR / "cache"
DRAFTS_DIR = DATA_DIR / "drafts"
INBOX_DIR = DATA_DIR / "inbox"

for _directory in (DATA_DIR, MEDIA_DIR, JOBS_DIR, CACHE_DIR, DRAFTS_DIR, INBOX_DIR):
    _directory.mkdir(parents=True, exist_ok=True)

BOT_TOKEN = _env(
    "TELEGRAM_BOT_TOKEN",
    "8823261756:AAH9xczdNpqdb_fDQXEDd4Ft_JA0an8yuYw",
)

ALLOWED_USER_IDS = [int(x) for x in _env("ALLOWED_USER_IDS", "").replace(",", ";").split(";") if x.strip().lstrip("-").isdigit()]

QWEN_API_KEY = _env(
    "QWEN_API_KEY",
    "sk-ws-H.DDDPDML.NWLk.MEUCIQDWo9EehUUeap-FEoOzyw79zh7iS75Kzat7rXjhw8bcxQIgBIE6LNMqm4efyKxVSZ57_xhmhoWUDDe1Yl6Xb53Pdrc",
)
QWEN_BASE_URL = _env("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
QWEN_TEXT_MODELS = _env_list("QWEN_TEXT_MODELS", ["qwen3.8-max", "qwen3.8-flash", "qwen3.7-max", "qwen-plus"])
QWEN_FAST_MODELS = _env_list("QWEN_FAST_MODELS", ["qwen3.8-flash", "qwen3.7-flash", "qwen-flash", "qwen-plus"])
QWEN_VL_MODELS = _env_list("QWEN_VL_MODELS", ["qwen3.8-max", "qwen3.8-flash", "qwen3-vl-plus", "qwen-vl-max"])
QWEN_TIMEOUT = _env_int("QWEN_TIMEOUT", 420)
QWEN_WRITE_THINKING = _env_int("QWEN_WRITE_THINKING", 3000)
QWEN_MAX_CHARS = _env_int("QWEN_MAX_CHARS", 60000)
QWEN_CHUNK_CHARS = _env_int("QWEN_CHUNK_CHARS", 45000)

BRAND_CONTEXT = _env(
    "BRAND_CONTEXT",
    "Piranusa (piranusa.com, tagline we get IT done) adalah perusahaan IT di Indonesia yang kontennya banyak membahas software desain seperti ZWCAD. Jangan menyebut Piranusa sebagai pembuat software pihak lain.",
)
ARTICLE_VOICE = _env(
    "ARTICLE_VOICE",
    "Santai tapi tetap profesional, seperti engineer senior yang menjelaskan ke rekan kerja. Sapa pembaca dengan kamu. Istilah teknis bahasa Inggris boleh dipakai apa adanya.",
)
MAX_INLINE_IMAGES = _env_int("MAX_INLINE_IMAGES", 2)

TRANSCRIPT_LANGUAGES = _env_list("TRANSCRIPT_LANGUAGES", ["id", "en"])
TRANSCRIPT_TIMEOUT = _env_int("TRANSCRIPT_TIMEOUT", 60)
YTDLP_PROXY = _env("YTDLP_PROXY", "")
YTDLP_COOKIES = _env("YTDLP_COOKIES", str(DATA_DIR / "cookies.txt"))

DEEPGRAM_API_KEY = _env("DEEPGRAM_API_KEY", "")
DEEPGRAM_MODEL = _env("DEEPGRAM_MODEL", "nova-3-general")
DEEPGRAM_TIMEOUT = _env_int("DEEPGRAM_TIMEOUT", 600)

FRAME_COUNT = _env_int("FRAME_COUNT", 10)
FRAME_MAX_HEIGHT = _env_int("FRAME_MAX_HEIGHT", 720)
FFMPEG_BIN = _env("FFMPEG_BIN", "ffmpeg")

MEDIA_HOST = _env("MEDIA_HOST", "0.0.0.0")
MEDIA_PORT = _env_int("MEDIA_PORT", 8055)
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "")
PUBLIC_BASE_URL_AUTO = _env("PUBLIC_BASE_URL_AUTO", "0") in ("1", "true", "yes", "on")

SITE_TITLE = _env("WP_SITE_TITLE", "Piranusa")
SITE_LINK = _env("WP_SITE_LINK", "https://www.piranusa.com")
SITE_LANGUAGE = _env("WP_SITE_LANGUAGE", "id-ID")
WP_AUTHOR_LOGIN = _env("WP_AUTHOR_LOGIN", "reza")
WP_AUTHOR_EMAIL = _env("WP_AUTHOR_EMAIL", "reza@contrivent.com")
WP_DEFAULT_CATEGORY = _env("WP_DEFAULT_CATEGORY", "Tips & Tutorial")
WP_DEFAULT_TAG = _env("WP_DEFAULT_TAG", "Transkrip Video")

WP_URL = _env("WP_URL", "")
WP_USER = _env("WP_USER", "")
WP_APP_PASSWORD = _env("WP_APP_PASSWORD", "")
WP_STATUS = _env("WP_STATUS", "draft")

REQUEST_TIMEOUT = _env_int("REQUEST_TIMEOUT", 60)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
