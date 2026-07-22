import hashlib
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import (
    CACHE_PATH,
    GOOGLE_CSE_API_KEY,
    GOOGLE_CSE_CX,
    MAX_SOURCES_PER_CASE,
    REQUEST_TIMEOUT,
    SEARCH_CACHE_HOURS,
    USER_AGENT,
)

GOOGLE_CSE_ENDPOINT = 'https://www.googleapis.com/customsearch/v1'

OFFICIAL_HINTS = (
    '.gov', 'police.uk', 'fbi.gov', 'justice.gov', 'interpol.int',
    'namus.nij.ojp.gov', 'statepolice', 'sheriff', 'police.',
)
TRUSTED_NEWS = (
    'reuters.com', 'apnews.com', 'bbc.com', 'bbc.co.uk', 'cbc.ca',
    'abc.net.au', 'theguardian.com', 'nbcnews.com', 'cbsnews.com',
    'abcnews.go.com', 'cnn.com', 'foxnews.com', 'newsweek.com',
    'globalnews.ca', 'ctvnews.ca', 'wikipedia.org',
)
BLOCKED_DOMAINS = (
    'google.com', 'news.google.com', 'youtube.com', 'youtu.be',
    'facebook.com', 'instagram.com', 'tiktok.com', 'x.com',
    'twitter.com', 'reddit.com', 'pinterest.com',
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


def _clean_url(url: str) -> str:
    url = html.unescape((url or '').strip())
    if not url.startswith(('http://', 'https://')):
        return ''
    if any(x in domain(url) for x in BLOCKED_DOMAINS):
        return ''
    return url.split('#', 1)[0]


def _result(title: str, url: str, snippet: str = '', source_name: str = '') -> dict | None:
    clean = _clean_url(url)
    if not clean:
        return None
    score, source_type = reliability(clean)
    return {
        'title': BeautifulSoup(title or '', 'lxml').get_text(' ', strip=True),
        'url': clean,
        'published_at': '',
        'summary': BeautifulSoup(snippet or '', 'lxml').get_text(' ', strip=True),
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
        logging.debug('Không lưu được cache tìm kiếm: %s', exc)


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode('utf-8')).hexdigest()


def google_cse_search(query: str, limit: int) -> list[dict]:
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        raise RuntimeError(
            'Thiếu GOOGLE_CSE_API_KEY hoặc GOOGLE_CSE_CX trong agent1/.env'
        )

    cache = _load_cache()
    key = _cache_key(query)
    cached = cache.get(key)
    if cached:
        try:
            saved_at = datetime.fromisoformat(cached['saved_at'])
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - saved_at < timedelta(hours=SEARCH_CACHE_HOURS):
                return cached.get('items', [])[:limit]
        except Exception:
            pass

    output: list[dict] = []
    start = 1
    while len(output) < limit and start <= 91:
        num = min(10, limit - len(output))
        response = requests.get(
            GOOGLE_CSE_ENDPOINT,
            params={
                'key': GOOGLE_CSE_API_KEY,
                'cx': GOOGLE_CSE_CX,
                'q': query,
                'num': num,
                'start': start,
                'safe': 'active',
                'filter': '1',
            },
            timeout=REQUEST_TIMEOUT,
            headers={'User-Agent': USER_AGENT},
        )
        if response.status_code == 429:
            raise RuntimeError('Google Custom Search đã hết quota hoặc bị giới hạn 429')
        response.raise_for_status()
        data = response.json()
        items = data.get('items', [])
        if not items:
            break
        for item in items:
            result = _result(
                item.get('title', ''),
                item.get('link', ''),
                item.get('snippet', ''),
                domain(item.get('link', '')),
            )
            if result:
                output.append(result)
        start += len(items)
        if len(items) < num:
            break

    cache[key] = {
        'saved_at': datetime.now(timezone.utc).isoformat(),
        'items': output,
    }
    _save_cache(cache)
    return output[:limit]


def search_sources(case_name: str, country: str = '') -> list[dict]:
    queries = [
        f'"{case_name}" {country} police investigation',
        f'"{case_name}" {country} unsolved case murder disappearance',
        f'"{case_name}" {country} official police sheriff FBI',
    ]

    candidates: list[dict] = []
    for query in queries:
        try:
            candidates.extend(google_cse_search(query, MAX_SOURCES_PER_CASE * 2))
        except Exception as exc:
            logging.warning('Google CSE lỗi với truy vấn %r: %s', query, exc)

    dedup: dict[str, dict] = {}
    normalized_name = re.sub(r'\W+', ' ', case_name.lower()).strip()
    tokens = [x for x in normalized_name.split() if len(x) >= 4]

    for item in candidates:
        url = item.get('url', '')
        if not url:
            continue
        haystack = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        relevance = sum(token in haystack for token in tokens)
        item['relevance_score'] = relevance
        key = url.rstrip('/')
        current = dedup.get(key)
        if current is None or (
            item['reliability_score'], item['relevance_score']
        ) > (
            current['reliability_score'], current.get('relevance_score', 0)
        ):
            dedup[key] = item

    results = list(dedup.values())
    results.sort(
        key=lambda x: (
            x['reliability_score'],
            x.get('relevance_score', 0),
        ),
        reverse=True,
    )
    return results[:MAX_SOURCES_PER_CASE]


def _json_ld_text(soup: BeautifulSoup) -> str:
    chunks: list[str] = []
    for node in soup.find_all('script', type='application/ld+json'):
        raw = node.string or node.get_text(' ', strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        for item in stack:
            if not isinstance(item, dict):
                continue
            graph = item.get('@graph')
            if isinstance(graph, list):
                stack.extend(x for x in graph if isinstance(x, dict))
            for key in ('articleBody', 'description'):
                value = item.get(key)
                if isinstance(value, str) and len(value) > 100:
                    chunks.append(value)
    return ' '.join(chunks)


def extract_text(url: str) -> str:
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                'User-Agent': USER_AGENT,
                'Accept-Language': 'en-US,en;q=0.9',
            },
            allow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if 'html' not in content_type and content_type:
            return ''

        soup = BeautifulSoup(response.text, 'lxml')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'noscript']):
            tag.decompose()

        candidates: list[str] = []
        ld_text = _json_ld_text(soup)
        if ld_text:
            candidates.append(ld_text)

        container = soup.find('article') or soup.find('main')
        if container:
            paragraphs = [p.get_text(' ', strip=True) for p in container.find_all('p')]
            candidates.append(' '.join(x for x in paragraphs if len(x) >= 30))

        all_paragraphs = [p.get_text(' ', strip=True) for p in soup.find_all('p')]
        candidates.append(' '.join(x for x in all_paragraphs if len(x) >= 30))

        best = max(candidates, key=len, default='')
        return ' '.join(best.split())[:16000]
    except Exception as exc:
        logging.debug('Không trích xuất được %s: %s', url, exc)
        return ''
