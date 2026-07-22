import html
import json
import logging
import re
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from config import MAX_SOURCES_PER_CASE, REQUEST_TIMEOUT, USER_AGENT

OFFICIAL_HINTS = (
    '.gov', 'police.uk', 'fbi.gov', 'justice.gov', 'interpol.int',
    'namus.nij.ojp.gov', 'statepolice', 'sheriff', 'police.',
)
TRUSTED_NEWS = (
    'reuters.com', 'apnews.com', 'bbc.com', 'bbc.co.uk', 'cbc.ca',
    'abc.net.au', 'theguardian.com', 'nbcnews.com', 'cbsnews.com',
    'abcnews.go.com', 'cnn.com', 'foxnews.com', 'newsweek.com',
)
BLOCKED_DOMAINS = (
    'google.com', 'news.google.com', 'duckduckgo.com', 'bing.com',
    'youtube.com', 'youtu.be', 'facebook.com', 'instagram.com',
    'tiktok.com', 'x.com', 'twitter.com', 'reddit.com',
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
    if not url:
        return ''
    parsed = urlparse(url)
    if 'duckduckgo.com' in parsed.netloc:
        target = parse_qs(parsed.query).get('uddg', [''])[0]
        if target:
            url = unquote(target)
    if url.startswith('//'):
        url = 'https:' + url
    if not url.startswith(('http://', 'https://')):
        return ''
    if any(x in domain(url) for x in BLOCKED_DOMAINS):
        return ''
    return url


def _result(title: str, url: str, source_name: str = '', published_at: str = '') -> dict | None:
    clean = _clean_url(url)
    if not clean:
        return None
    score, source_type = reliability(clean)
    return {
        'title': BeautifulSoup(title or '', 'lxml').get_text(' ', strip=True),
        'url': clean,
        'published_at': published_at or '',
        'source_name': source_name or domain(clean),
        'reliability_score': score,
        'source_type': source_type,
    }


def duckduckgo_search(query: str, limit: int) -> list[dict]:
    """Tìm URL gốc bằng DuckDuckGo HTML, không cần API key."""
    url = 'https://html.duckduckgo.com/html/?q=' + quote_plus(query)
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={
            'User-Agent': USER_AGENT,
            'Accept-Language': 'en-US,en;q=0.9',
        },
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'lxml')
    output: list[dict] = []
    for node in soup.select('a.result__a, a[data-testid="result-title-a"]'):
        item = _result(node.get_text(' ', strip=True), node.get('href', ''))
        if item:
            output.append(item)
        if len(output) >= limit:
            break
    return output


def google_news_titles(query: str, limit: int) -> list[dict]:
    """Chỉ dùng Google News để lấy tiêu đề gợi ý, không dùng link trung gian làm nguồn."""
    url = (
        'https://news.google.com/rss/search?q=' + quote_plus(query)
        + '&hl=en-US&gl=US&ceid=US:en'
    )
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={'User-Agent': USER_AGENT},
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    output: list[dict] = []
    for entry in feed.entries[:limit]:
        source_name = ''
        try:
            source_name = entry.get('source', {}).get('title', '')
        except Exception:
            pass
        output.append({
            'title': str(entry.get('title', '')).strip(),
            'source_name': source_name,
            'published_at': str(entry.get('published', '')).strip(),
        })
    return output


def search_sources(case_name: str, country: str = '') -> list[dict]:
    """Tìm URL bài gốc, ưu tiên nguồn chính thức và báo uy tín."""
    queries = [
        f'"{case_name}" {country} police investigation',
        f'"{case_name}" {country} unsolved case',
        f'"{case_name}" {country} site:gov OR site:police OR site:sheriff',
    ]
    candidates: list[dict] = []
    for query in queries:
        try:
            candidates.extend(duckduckgo_search(query, MAX_SOURCES_PER_CASE * 2))
        except Exception as exc:
            logging.warning('DuckDuckGo lỗi với truy vấn %r: %s', query, exc)

    # Nếu tìm trực tiếp còn ít, lấy tiêu đề Google News rồi tìm lại URL gốc theo tiêu đề.
    if len(candidates) < MAX_SOURCES_PER_CASE:
        try:
            hints = google_news_titles(queries[0], MAX_SOURCES_PER_CASE * 2)
            for hint in hints:
                title = re.sub(r'\s+-\s+[^-]{2,80}$', '', hint['title']).strip()
                if not title:
                    continue
                try:
                    found = duckduckgo_search(f'"{title}"', 3)
                    for item in found:
                        if hint.get('source_name') and not item.get('source_name'):
                            item['source_name'] = hint['source_name']
                        if hint.get('published_at') and not item.get('published_at'):
                            item['published_at'] = hint['published_at']
                        candidates.append(item)
                except Exception as exc:
                    logging.debug('Không tìm được URL gốc cho %r: %s', title, exc)
        except Exception as exc:
            logging.warning('Google News gợi ý lỗi: %s', exc)

    dedup: dict[str, dict] = {}
    for item in candidates:
        url = item.get('url', '')
        if not url:
            continue
        key = url.split('#', 1)[0].rstrip('/')
        current = dedup.get(key)
        if current is None or item['reliability_score'] > current['reliability_score']:
            dedup[key] = item

    results = list(dedup.values())
    results.sort(key=lambda x: (x['reliability_score'], x['source_type'] == 'official'), reverse=True)
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
            for key in ('articleBody', 'description'):
                value = item.get(key)
                if isinstance(value, str) and len(value) > 100:
                    chunks.append(value)
    return ' '.join(chunks)


def extract_text(url: str) -> str:
    """Tải nội dung từ URL gốc; ưu tiên article/main và đoạn văn."""
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
        candidates.append(soup.get_text(' ', strip=True))

        best = max(candidates, key=len, default='')
        return ' '.join(best.split())[:16000]
    except Exception as exc:
        logging.debug('Không trích xuất được %s: %s', url, exc)
        return ''
