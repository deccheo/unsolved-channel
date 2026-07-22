from urllib.parse import quote_plus, urlparse
import feedparser
import requests
from bs4 import BeautifulSoup
from config import REQUEST_TIMEOUT, USER_AGENT, MAX_SOURCES_PER_CASE

OFFICIAL_HINTS = (
    '.gov', 'police.uk', 'fbi.gov', 'justice.gov', 'interpol.int',
    'namus.nij.ojp.gov', 'statepolice', 'sheriff', 'police.',
)
TRUSTED_NEWS = (
    'reuters.com', 'apnews.com', 'bbc.com', 'bbc.co.uk', 'cbc.ca',
    'abc.net.au', 'theguardian.com', 'nbcnews.com', 'cbsnews.com',
)


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix('www.')


def reliability(url: str) -> tuple[int, str]:
    d = domain(url)
    if any(x in d for x in OFFICIAL_HINTS):
        return 100, 'official'
    if any(d == x or d.endswith('.' + x) for x in TRUSTED_NEWS):
        return 90, 'trusted_news'
    return 55, 'secondary'


def google_news(case_name: str, country: str = '') -> list[dict]:
    query = f'"{case_name}" {country} police investigation'
    url = 'https://news.google.com/rss/search?q=' + quote_plus(query) + '&hl=en-US&gl=US&ceid=US:en'
    r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={'User-Agent': USER_AGENT})
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    results: list[dict] = []
    seen: set[str] = set()
    for entry in feed.entries[:MAX_SOURCES_PER_CASE * 3]:
        link = str(entry.get('link','')).strip()
        if not link or link in seen:
            continue
        seen.add(link)
        source = ''
        try:
            source = entry.get('source', {}).get('title', '')
        except Exception:
            pass
        score, source_type = reliability(link)
        results.append({
            'title': str(entry.get('title','')).strip(),
            'url': link,
            'published_at': str(entry.get('published','')).strip(),
            'summary': str(entry.get('summary','')).strip(),
            'source_name': source,
            'reliability_score': score,
            'source_type': source_type,
        })
    results.sort(key=lambda x: x['reliability_score'], reverse=True)
    return results[:MAX_SOURCES_PER_CASE]


def extract_text(url: str) -> str:
    try:
        r = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={'User-Agent': USER_AGENT},
            allow_redirects=True,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')
        for tag in soup(['script','style','nav','footer','header','aside','form']):
            tag.decompose()
        return ' '.join(soup.get_text(' ').split())[:12000]
    except Exception:
        return ''
