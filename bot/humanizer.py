import re
from functools import lru_cache

import config

RULES_FILE = config.BASE_DIR / "prompts" / "humanizer.md"

WATCHED = (
    "merupakan",
    "memainkan peran",
    "krusial",
    "signifikan",
    "holistik",
    "komprehensif",
    "efektif dan efisien",
    "menjadi kunci",
    "tak hanya",
    "tidak hanya",
    "melainkan juga",
    "tetapi juga",
    "bukan sekadar",
    "tentunya",
    "adapun",
    "di era digital",
    "era modern",
    "tak dapat dipungkiri",
    "tidak dapat dipungkiri",
    "seiring dengan",
    "seiring berjalannya waktu",
    "dalam beberapa tahun terakhir",
    "sebagai kesimpulan",
    "dengan demikian",
    "pada akhirnya",
    "semoga bermanfaat",
    "semoga artikel ini",
    "mari kita",
    "yuk simak",
    "yuk kita",
    "berikut adalah",
    "berikut ini adalah",
    "solusi terbaik",
    "revolusioner",
    "luar biasa",
    "memukau",
    "menawan",
    "yang menunjukkan",
    "yang mencerminkan",
    "yang menegaskan",
    "sekaligus memperkuat",
    "melakukan pengecekan",
    "memberikan penjelasan",
    "mengalami peningkatan",
    "dalam rangka",
    "pada dasarnya",
    "pada intinya",
    "secara fundamental",
    "game changer",
    "tanpa ribet",
    "hadir sebagai",
    "menghadirkan",
    "mengusung",
    "menjadi sorotan",
    "membuka jalan",
    "tonggak",
    "lanskap",
    "jujur ya",
    "gini deh",
    "perlu diketahui",
    "sejauh informasi",
)

JOIN_PREFIXES = (
    "non", "anti", "pasca", "pra", "antar", "multi", "semi", "sub", "super",
    "ultra", "swa", "inter", "trans", "kontra", "eks", "mikro", "makro", "neo",
)

KEEP_HYPHEN = {
    "e-commerce", "e-mail", "e-book", "e-katalog", "e-learning", "e-wallet",
    "wi-fi", "t-shirt", "x-ray", "k-pop", "add-on", "add-ons", "plug-in",
}

ORDINALS = {
    "1": "pertama", "2": "kedua", "3": "ketiga", "4": "keempat", "5": "kelima",
    "6": "keenam", "7": "ketujuh", "8": "kedelapan", "9": "kesembilan", "10": "kesepuluh",
}

DASH_CHARS = "‒–—―−"
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U0001FC00-\U0001FFFF☀-➿⬀-⯿⌀-⏿️‍⃣←-⇿✅✔✖]"
)
TIMESTAMP_RE = re.compile(
    r"\s*[\[(]\s*(?:menit\s+|detik\s+)?\d{1,2}:\d{2}(?::\d{2})?"
    r"(?:\s*(?:[" + DASH_CHARS + r"\x2d]|sampai|hingga|s/d)\s*\d{1,2}:\d{2}(?::\d{2})?)?\s*[\])]",
    re.IGNORECASE,
)
PROTECT_RE = re.compile(
    r"https?://\S+|www\.\S+|`[^`]*`|[\w./]*\d[\w./]*(?:\x2d[\w./]+)+|\b[A-Z][A-Z0-9]+(?:\x2d[A-Z0-9]+)+\b"
)
RANGE_RE = re.compile(
    r"(?<![\w\x2d])((?:Rp\s?)?\d[\d.,]*)\s*[" + DASH_CHARS + r"\x2d]\s*((?:Rp\s?)?\d[\d.,]*)(?![\w\x2d])"
)
QUOTE_MAP = {
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "…": "...", "•": "", "·": "", " ": " ",
}


@lru_cache(maxsize=1)
def rules():
    try:
        text = RULES_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    return text.strip()


def _range(match):
    left, right = match.group(1), match.group(2)
    return "%s sampai %s" % (left, right)


def _word_hyphen(match):
    left, right = match.group(1), match.group(2)
    token = "%s\x2d%s" % (left, right)
    if token.lower() in KEEP_HYPHEN:
        return token
    if left.lower() == right.lower():
        return "%s %s" % (left, right)
    if right.lower() in ("nya", "ku", "mu", "lah", "kah", "pun"):
        return left + right
    low = left.lower()
    if low in ("di", "ke", "se"):
        if low == "se" and right[:1].isupper():
            return "seluruh %s" % right
        if low == "ke" and right in ORDINALS:
            return ORDINALS[right]
        return left + right
    if low in JOIN_PREFIXES:
        if right[:1].isupper():
            return "%s %s" % (left, right)
        return left + right
    return "%s %s" % (left, right)


def _hyphens(text):
    text = RANGE_RE.sub(_range, text)
    text = re.sub(r"(\d)\x2dan\b", r"\1an", text)
    text = re.sub(r"\bke\x2d(\d{1,2})\b", lambda m: ORDINALS.get(m.group(1), "ke" + m.group(1)), text, flags=re.IGNORECASE)
    stash = []

    def keep(match):
        stash.append(match.group(0))
        return "\x00%d\x00" % (len(stash) - 1)

    text = PROTECT_RE.sub(keep, text)
    for _ in range(3):
        text = re.sub(r"([^\W\d_]+)\x2d([^\W_]+)", _word_hyphen, text)
    text = re.sub(r"\s*\x2d{2,}\s*", ", ", text)
    text = re.sub(r"\s+\x2d\s+", ", ", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
    return text


def _dashes(text):
    text = re.sub(r"\s*[" + DASH_CHARS + r"]\s*", ", ", text)
    return text


def _semicolons(text):
    return re.sub(r"\s*;\s*(\S)", lambda m: ". " + m.group(1)[:1].upper() + m.group(1)[1:], text).replace(";", ".")


def _tidy(text):
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.:!?)])", r"\1", text)
    text = re.sub(r"([(])\s+", r"\1", text)
    text = re.sub(r",\s*,+", ",", text)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(r"\.\s*,", ".", text)
    text = re.sub(r":\s*,", ":", text)
    text = re.sub(r"^[,.;:\s]+", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    return text.strip()


def sanitize(text):
    if not text:
        return ""
    text = str(text)
    for src, dst in QUOTE_MAP.items():
        text = text.replace(src, dst)
    text = EMOJI_RE.sub("", text)
    text = TIMESTAMP_RE.sub("", text)
    text = _hyphens(text)
    text = _dashes(text)
    text = _semicolons(text)
    text = re.sub(r"^\s*(?:[\x2d*]|\d+[.)])\s+", "", text)
    return _tidy(text)


def sanitize_title(text, keep=()):
    text = sanitize(text)
    text = text.rstrip(".")
    text = re.sub(r"!{2,}", "!", text)
    text = re.sub(r"\?{2,}", "?", text)
    if text.isupper() and len(text) > 12:
        text = text.capitalize()
    return sentence_case(text, keep)


def _simple_title(word):
    core = word.rstrip(",:?!")
    return bool(re.fullmatch(r"[^\W\d_]+", core)) and core[0].isupper() and (len(core) == 1 or core[1:].islower())


def sentence_case(text, keep=()):
    words = text.split(" ")
    plain = [w for w in words[1:] if re.fullmatch(r"[^\W\d_]{3,}[,:?!]?", w) and (w.rstrip(",:?!").islower() or _simple_title(w))]
    if len(plain) < 3:
        return text
    titled = [w for w in plain if _simple_title(w)]
    if len(titled) / float(len(plain)) < 0.6:
        return text
    out = [words[0]]
    after_colon = False
    for word in words[1:]:
        if _simple_title(word) and not after_colon and word.rstrip(",:?!") not in keep:
            word = word[0].lower() + word[1:]
        out.append(word)
        after_colon = word.endswith(":")
    return " ".join(out)


def proper_words(text):
    counts = {}
    for match in re.finditer(r"(?<=[a-z,] )([A-Z][a-z]{2,})\b", text or ""):
        counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    return {word for word, count in counts.items() if count >= 2}


def ai_smell(text):
    lowered = " %s " % (text or "").lower()
    hits = []
    for phrase in WATCHED:
        if re.search(r"(?<!\w)%s(?!\w)" % re.escape(phrase), lowered):
            hits.append(phrase)
    return hits


def forbidden_chars(text):
    stripped = PROTECT_RE.sub("", text or "")
    found = []
    for char in DASH_CHARS + ";…“”‘’":
        if char in stripped:
            found.append(char)
    if re.search(r"[^\W\d_]\x2d[^\W\d_]", stripped):
        found.append("\x2d")
    if EMOJI_RE.search(stripped):
        found.append("emoji")
    return found
