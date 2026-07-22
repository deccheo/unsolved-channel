import hashlib, html, json, logging, os, re, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urlparse, urlunparse
import feedparser, requests
from bs4 import BeautifulSoup
from config import CACHE_PATH, MAX_SOURCES_PER_CASE, REQUEST_TIMEOUT, SEARCH_CACHE_HOURS, USER_AGENT

OFFICIAL_HINTS = ('.gov','police.uk','fbi.gov','justice.gov','interpol.int','namus.nij.ojp.gov','statepolice','sheriff','police.')
TRUSTED_NEWS = ('reuters.com','apnews.com','bbc.com','bbc.co.uk','cbc.ca','abc.net.au','theguardian.com','nbcnews.com','cbsnews.com','abcnews.go.com','cnn.com','foxnews.com','globalnews.ca','ctvnews.ca','msn.com')
BLOCKED_DOMAINS = ('youtube.com','youtu.be','facebook.com','instagram.com','tiktok.com','x.com','twitter.com','reddit.com','pinterest.com')
TRACKING_PARAMS = {'utm_source','utm_medium','utm_campaign','utm_term','utm_content','gclid','fbclid','oc'}

def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix('www.')

def reliability(url: str) -> tuple[int,str]:
    d = domain(url)
    if any(x in d for x in OFFICIAL_HINTS): return 100,'official'
    if any(d == x or d.endswith('.'+x) for x in TRUSTED_NEWS): return 90,'trusted_news'
    return 55,'secondary'

def _unwrap_redirect(url: str) -> str:
    url = html.unescape((url or '').strip()); parsed = urlparse(url); query = parse_qs(parsed.query)
    for key in ('url','u','target','r'):
        value = query.get(key,[''])[0]
        if value.startswith(('http://','https://')): return unquote(value)
    return url

def _clean_url(url: str) -> str:
    url = _unwrap_redirect(url)
    if not url.startswith(('http://','https://')): return ''
    parsed = urlparse(url); d = parsed.netloc.lower().removeprefix('www.')
    if any(x in d for x in BLOCKED_DOMAINS): return ''
    clean_q = [(k,v) for k,v in parse_qs(parsed.query,keep_blank_values=True).items() if k.lower() not in TRACKING_PARAMS]
    query = urlencode([(k,item) for k,vals in clean_q for item in vals],doseq=True)
    return urlunparse((parsed.scheme,parsed.netloc,parsed.path,'',query,''))

def _plain(value: str) -> str:
    return BeautifulSoup(value or '','lxml').get_text(' ',strip=True)

def _result(title: str,url: str,summary: str='',source_name: str='',published_at: str=''):
    clean = _clean_url(url)
    if not clean: return None
    score,stype = reliability(clean)
    return {'title':_plain(title),'url':clean,'published_at':published_at or '','summary':_plain(summary),
            'source_name':source_name or domain(clean),'reliability_score':score,'source_type':stype}

def _load_cache() -> dict:
    try:
        value=json.loads(Path(CACHE_PATH).read_text(encoding='utf-8')); return value if isinstance(value,dict) else {}
    except Exception: return {}

def _save_cache(cache: dict) -> None:
    path=Path(CACHE_PATH); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(cache,f,ensure_ascii=False)
        os.replace(tmp,path)
    except Exception as exc:
        try: os.unlink(tmp)
        except OSError: pass
        logging.debug('Không lưu được cache: %s',exc)

def _key(query: str) -> str: return hashlib.sha256(query.encode()).hexdigest()
def _cached(query: str):
    item=_load_cache().get(_key(query))
    if not item: return None
    try:
        saved=datetime.fromisoformat(item['saved_at']); saved=saved if saved.tzinfo else saved.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc)-saved < timedelta(hours=SEARCH_CACHE_HOURS): return item.get('items',[])
    except Exception: pass
    return None

def _save_query(query: str,items: list[dict]):
    cache=_load_cache(); cache[_key(query)]={'saved_at':datetime.now(timezone.utc).isoformat(),'items':items}; _save_cache(cache)

def bing_news_rss(query: str,limit: int) -> list[dict]:
    r=requests.get('https://www.bing.com/news/search',params={'q':query,'format':'rss','setlang':'en-us'},timeout=REQUEST_TIMEOUT,headers={'User-Agent':USER_AGENT})
    r.raise_for_status(); feed=feedparser.parse(r.content); out=[]
    for e in feed.entries[:limit*2]:
        item=_result(e.get('title',''),e.get('link',''),e.get('summary',''),'',e.get('published',''))
        if item and domain(item['url'])!='bing.com': out.append(item)
        if len(out)>=limit: break
    return out

def _resolve_google_news(url: str) -> str:
    try:
        r=requests.get(url,timeout=REQUEST_TIMEOUT,headers={'User-Agent':USER_AGENT},allow_redirects=True)
        if domain(r.url) not in ('news.google.com','google.com'): return _clean_url(r.url)
        soup=BeautifulSoup(r.text,'lxml')
        for selector,attr in [('link[rel="canonical"]','href'),('meta[property="og:url"]','content')]:
            node=soup.select_one(selector); candidate=node.get(attr,'') if node else ''
            if candidate and domain(candidate) not in ('news.google.com','google.com'): return _clean_url(candidate)
    except Exception: pass
    return ''

def google_news_rss(query: str,limit: int) -> list[dict]:
    r=requests.get('https://news.google.com/rss/search',params={'q':query,'hl':'en-US','gl':'US','ceid':'US:en'},timeout=REQUEST_TIMEOUT,headers={'User-Agent':USER_AGENT})
    r.raise_for_status(); feed=feedparser.parse(r.content); out=[]
    for e in feed.entries[:limit*2]:
        original=_resolve_google_news(e.get('link',''))
        if not original: continue
        source=''
        try: source=e.get('source',{}).get('title','')
        except Exception: pass
        item=_result(e.get('title',''),original,e.get('summary',''),source,e.get('published',''))
        if item: out.append(item)
        if len(out)>=limit: break
    return out

def gdelt_search(query: str,limit: int) -> list[dict]:
    r=requests.get('https://api.gdeltproject.org/api/v2/doc/doc',params={'query':query,'mode':'artlist','maxrecords':min(limit,25),'format':'json','sourcelang':'english'},timeout=REQUEST_TIMEOUT,headers={'User-Agent':USER_AGENT})
    if r.status_code==429: logging.info('GDELT giới hạn 429, bỏ qua'); return []
    r.raise_for_status(); out=[]
    for a in r.json().get('articles',[]):
        item=_result(a.get('title',''),a.get('url',''),'',a.get('domain',''),a.get('seendate',''))
        if item: out.append(item)
    return out[:limit]

def search_sources(case_name: str,country: str='') -> list[dict]:
    case_name=' '.join(str(case_name).split())
    if not case_name: return []
    query=f'"{case_name}" {country} police investigation unsolved case'.strip()
    cached=_cached(query)
    if cached is not None: return cached[:MAX_SOURCES_PER_CASE]
    candidates=[]
    for fn in (bing_news_rss,google_news_rss,gdelt_search):
        try: candidates.extend(fn(query,MAX_SOURCES_PER_CASE*2))
        except Exception as exc: logging.warning('%s lỗi: %s',fn.__name__,exc)
        time.sleep(.25)
    tokens=[x for x in re.sub(r'\W+',' ',case_name.lower()).split() if len(x)>=4]
    dedup={}
    for item in candidates:
        hay=f"{item.get('title','')} {item.get('summary','')}".lower()
        item['relevance_score']=sum(1 for token in tokens if token in hay)
        key=item['url'].rstrip('/').lower(); old=dedup.get(key)
        if old is None or (item['reliability_score'],item['relevance_score'])>(old['reliability_score'],old.get('relevance_score',0)): dedup[key]=item
    results=sorted(dedup.values(),key=lambda x:(x['reliability_score'],x.get('relevance_score',0)),reverse=True)[:MAX_SOURCES_PER_CASE]
    _save_query(query,results); return results

def _json_ld_text(soup: BeautifulSoup) -> str:
    chunks=[]
    for node in soup.find_all('script',type='application/ld+json'):
        raw=node.string or node.get_text(' ',strip=True)
        if not raw: continue
        try: data=json.loads(raw)
        except Exception: continue
        stack=data if isinstance(data,list) else [data]
        for item in list(stack):
            if not isinstance(item,dict): continue
            if isinstance(item.get('@graph'),list): stack.extend(x for x in item['@graph'] if isinstance(x,dict))
            for key in ('articleBody','description'):
                value=item.get(key)
                if isinstance(value,str) and len(value)>100: chunks.append(value)
    return ' '.join(chunks)

def extract_text(url: str) -> str:
    try:
        r=requests.get(url,timeout=REQUEST_TIMEOUT,headers={'User-Agent':USER_AGENT,'Accept-Language':'en-US,en;q=0.9'},allow_redirects=True)
        r.raise_for_status(); ctype=r.headers.get('content-type','').lower()
        if ctype and 'html' not in ctype: return ''
        soup=BeautifulSoup(r.text,'lxml')
        for tag in soup(['script','style','nav','footer','header','aside','form','noscript']): tag.decompose()
        candidates=[_json_ld_text(soup)]
        container=soup.find('article') or soup.find('main')
        if container: candidates.append(' '.join(p.get_text(' ',strip=True) for p in container.find_all('p')))
        candidates.append(' '.join(p.get_text(' ',strip=True) for p in soup.find_all('p')))
        return ' '.join(max(candidates,key=len,default='').split())[:20000]
    except Exception as exc:
        logging.debug('Không trích được %s: %s',url,exc); return ''
