from urllib.parse import quote_plus
import feedparser, requests
from config import SEARCH_QUERIES, MAX_ARTICLES_PER_QUERY, REQUEST_TIMEOUT, USER_AGENT
from utils import clean_text

def url_for(query: str) -> str:
    return "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"

def fetch(query: str) -> list[dict]:
    r = requests.get(url_for(query), timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    out = []
    for e in feed.entries[:MAX_ARTICLES_PER_QUERY]:
        source = ""
        try:
            source = clean_text(e.get("source", {}).get("title", ""))
        except Exception:
            pass
        out.append({
            "title": clean_text(e.get("title", "")),
            "url": str(e.get("link", "")).strip(),
            "published_at": clean_text(e.get("published", "")),
            "summary": clean_text(e.get("summary", "")),
            "source_name": source,
            "query": query,
        })
    return out

def collect() -> list[dict]:
    all_items = []
    for q in SEARCH_QUERIES:
        print(f"Đang tìm: {q}")
        try:
            items = fetch(q)
            print(f"  Tìm thấy {len(items)} bài")
            all_items.extend(items)
        except Exception as exc:
            print(f"  Lỗi RSS: {exc}")
    return all_items
