import hashlib
import html
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from config import CACHE_PATH, MAX_SOURCES_PER_CASE, REQUEST_TIMEOUT, SEARCH_CACHE_HOURS, USER_AGENT

OFFICIAL_HINTS = ('.gov', 'police.uk', 'fbi.gov', 'justice.gov', 'interpol.int', 'namus.nij.ojp.gov', 'statepolice', 'sheriff', 'police.')
TRUSTED_NEWS = ('reuters.com', 'apnews.com', 'bbc.com', 'bbc.co.uk', 'cbc.ca', 'abc.net.au', 'theguardian.com', 'nbcnews.com', 'cbsnews.com', 'abcnews.go.com', 'cnn.com', 'foxnews.com', 'globalnews.ca', 'ctvnews.ca')
BLOCKED_DOMAINS = ('youtube.com', 'youtu.be', 'facebook.com', 'instagram.com', 'tiktok.com', 'x.com', 'twitter.com', 'reddit.com', 'pinterest.com')


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix('www.')


def reliability(url: str) -> tuple[int, str]:
    d = domain(url)
    if any(x in d for x in OFFICIAL_HINTS):
        return 100, 'official'
    if any(d == x or d.endswith('.' + x) for x in TRUSTED_NEWS):
        return 90, 'trusted_news'
    return 55, 'secondary'


def _unwrap_redirect(url: str) -> str:
    url = html.unescape((url or '').strip())
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ('url', 'u', 'target', 'r'):
        value = query.get(key, [''])[0]
        if value.startswith(('http://', 'https://')):
            return unquote(value)
    return url


def _clean_url(url: str) -> str:
    url = _unwrap_redirect(url)
    if not url.startswith(('http://', 'https://')):
        return ''
    d = domain(url)
    if any(x in d for x in BLOCKED_DOMAINS):
        return ''
    return url.split('#', 1)[0]


def _result(title: str, url: str, summary: str = '', source_name: str = '', published_at: str = '') -> dict | None:
    clean = _clean_url(url)
    if not clean:
        return None
    score, source_type = reliability(clean)
    return {
        'title': BeautifulSoup(title or '', 'lxml').get_text(' ', strip=True),
        'url': clean,
        'published_at': published_at or '',
        'summary': BeautifulSoup(summary or '', 'lxml').get_text(' ', strip=True),
        'source_name': source_name or domain(clean),
        'reliability_score': score,
        'source_type': source_type,
    }


def _load_cache() -> dict:
    try:
        return json.loads(Path(CACHE_PATH).read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        Path(CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(CACHE_PATH).write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    except Exception as exc:
        logging.debug('Không lưu được cache V6: %s', exc)


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode('utf-8')).hexdigest()


def _cached(query: str):
    cache = _load_cache(); item = cache.get(_cache_key(query))
    if not item:
        return None
    try:
        saved = datetime.fromisoformat(item['saved_at'])
        if saved.tzinfo is None: saved = saved.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - saved < timedelta(hours=SEARCH_CACHE_HOURS):
            return item.get('items', [])
    except Exception:
        return None
    return None


def _save_query(query: str, items: list[dict]) -> None:
    cache = _load_cache(); cache[_cache_key(query)] = {'saved_at': datetime.now(timezone.utc).isoformat(), 'items': items}; _save_cache(cache)


def bing_news_rss(query: str, limit: int) -> list[dict]:
    url = 'https://www.bing.com/news/search?q=' + quote_plus(query) + '&format=rss&setlang=en-us'
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={'User-Agent': USER_AGENT, 'Accept-Language': 'en-US,en;q=0.9'})
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    out = []
    for entry in feed.entries[:limit * 2]:
        link = entry.get('link', '')
        item = _result(entry.get('title', ''), link, entry.get('summary', ''), '', entry.get('published', ''))
        if item and domain(item['url']) not in ('bing.com', 'www.bing.com'):
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _resolve_google_news(url: str) -> str:
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={'User-Agent': USER_AGENT}, allow_redirects=True)
        if domain(r.url) not in ('news.google.com', 'google.com'):
            return r.url
        soup = BeautifulSoup(r.text, 'lxml')
        for selector, attr in [('link[rel="canonical"]', 'href'), ('meta[property="og:url"]', 'content')]:
            node = soup.select_one(selector)
            candidate = node.get(attr, '') if node else ''
            if candidate and domain(candidate) not in ('news.google.com', 'google.com'):
                return candidate
        match = re.search(r'https?://[^"\\\s<>]+', r.text)
        if match and domain(match.group(0)) not in ('news.google.com', 'google.com'):
            return html.unescape(match.group(0))
    except Exception:
        pass
    return ''


def google_news_rss(query: str, limit: int) -> list[dict]:
    url = 'https://news.google.com/rss/search?q=' + quote_plus(query) + '&hl=en-US&gl=US&ceid=US:en'
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={'User-Agent': USER_AGENT})
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    out = []
    for entry in feed.entries[:limit * 2]:
        original = _resolve_google_news(entry.get('link', ''))
        if not original:
            continue
        source = ''
        try: source = entry.get('source', {}).get('title', '')
        except Exception: pass
        item = _result(entry.get('title', ''), original, entry.get('summary', ''), source, entry.get('published', ''))
        if item: out.append(item)
        if len(out) >= limit: break
    return out


def gdelt_search(query: str, limit: int) -> list[dict]:
    url = 'https://api.gdeltproject.org/api/v2/doc/doc'
    response = requests.get(url, params={'query': query, 'mode': 'artlist', 'maxrecords': min(limit, 25), 'format': 'json', 'sourcelang': 'english'}, timeout=REQUEST_TIMEOUT, headers={'User-Agent': USER_AGENT})
    if response.status_code == 429:
        logging.info('GDELT đang giới hạn 429, bỏ qua tầng dự phòng')
        return []
    response.raise_for_status()
    data = response.json(); out = []
    for article in data.get('articles', []):
        item = _result(article.get('title', ''), article.get('url', ''), '', article.get('domain', ''), article.get('seendate', ''))
        if item: out.append(item)
    return out[:limit]


def search_sources(case_name: str, country: str = '') -> list[dict]:
    query = f'"{case_name}" {country} police investigation unsolved case'.strip()
    cached = _cached(query)
    if cached is not None:
        return cached[:MAX_SOURCES_PER_CASE]
    candidates = []
    for fn in (bing_news_rss, google_news_rss, gdelt_search):
        try:
            candidates.extend(fn(query, MAX_SOURCES_PER_CASE * 2))
        except Exception as exc:
            logging.warning('%s lỗi: %s', fn.__name__, exc)
        time.sleep(1)
    tokens = [x for x in re.sub(r'\W+', ' ', case_name.lower()).split() if len(x) >= 4]
    dedup = {}
    for item in candidates:
        haystack = f"{item.get('title','')} {item.get('summary','')}".lower()
        item['relevance_score'] = sum(token in haystack for token in tokens)
        key = item['url'].rstrip('/')
        old = dedup.get(key)
        if old is None or (item['reliability_score'], item['relevance_score']) > (old['reliability_score'], old.get('relevance_score', 0)):
            dedup[key] = item
    results = list(dedup.values())
    results.sort(key=lambda x: (x['reliability_score'], x.get('relevance_score', 0)), reverse=True)
    results = results[:MAX_SOURCES_PER_CASE]
    _save_query(query, results)
    return results


def _json_ld_text(soup: BeautifulSoup) -> str:
    chunks = []
    for node in soup.find_all('script', type='application/ld+json'):
        raw = node.string or node.get_text(' ', strip=True)
        if not raw: continue
        try: data = json.loads(raw)
        except Exception: continue
        stack = data if isinstance(data, list) else [data]
        for item in stack:
            if not isinstance(item, dict): continue
            graph = item.get('@graph')
            if isinstance(graph, list): stack.extend(x for x in graph if isinstance(x, dict))
            for key in ('articleBody', 'description'):
                value = item.get(key)
                if isinstance(value, str) and len(value) > 100: chunks.append(value)
    return ' '.join(chunks)


def extract_text(url: str) -> str:
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={'User-Agent': USER_AGENT, 'Accept-Language': 'en-US,en;q=0.9'}, allow_redirects=True)
        response.raise_for_status()
        if response.headers.get('content-type') and 'html' not in response.headers.get('content-type', '').lower(): return ''
        soup = BeautifulSoup(response.text, 'lxml')
        for tag in soup(['script','style','nav','footer','header','aside','form','noscript']): tag.decompose()
        candidates = []
        ld = _json_ld_text(soup)
        if ld: candidates.append(ld)
        container = soup.find('article') or soup.find('main')
        if container:
            candidates.append(' '.join(p.get_text(' ', strip=True) for p in container.find_all('p')))
        candidates.append(' '.join(p.get_text(' ', strip=True) for p in soup.find_all('p')))
        text = max(candidates, key=len, default='')
        return ' '.join(text.split())[:20000]
    except Exception as exc:
        logging.debug('Không trích được %s: %s', url, exc)
        return ''
