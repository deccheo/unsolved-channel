import hashlib, html, re, unicodedata

def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def normalize_title(title: str) -> str:
    text = clean_text(title).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s[-|–—]\s[^-|–—]{2,80}$", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def case_key(title: str, url: str) -> str:
    raw = f"{normalize_title(title)}|{url}"
    return hashlib.sha256(raw.encode()).hexdigest()

def clamp(v) -> int:
    try:
        return max(0, min(100, int(float(v))))
    except Exception:
        return 0
