from rapidfuzz import fuzz
from database import existing_titles, key_exists
from utils import normalize_title, case_key

BLOCKED = {"movie","film","netflix","episode","series","fiction","novel","game","trailer","review","podcast"}
REQUIRED = {"unsolved","cold case","missing","disappearance","disappeared","unidentified","homicide","murder","investigation"}

def filter_items(items: list[dict]) -> list[dict]:
    known = existing_titles()
    accepted, accepted_titles = [], []
    for item in items:
        title, url = item.get("title",""), item.get("url","")
        text = f"{title} {item.get('summary','')}".lower()
        if not title or not url:
            continue
        if any(w in text for w in BLOCKED):
            continue
        if not any(w in text for w in REQUIRED):
            continue
        norm = normalize_title(title)
        if len(norm) < 15:
            continue
        key = case_key(title, url)
        if key_exists(key):
            continue
        if any(fuzz.token_set_ratio(norm, x) >= 90 for x in known):
            continue
        if any(fuzz.token_set_ratio(norm, x) >= 90 for x in accepted_titles):
            continue
        item["normalized_title"] = norm
        item["case_key"] = key
        accepted.append(item)
        accepted_titles.append(norm)
    return accepted
