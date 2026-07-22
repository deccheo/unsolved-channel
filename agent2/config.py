import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(os.getenv('UNSOLVED_BASE_DIR', '/opt/unsolved-channel')).resolve()
AGENT1_DIR = BASE_DIR / 'agent1'
DB_PATH = Path(os.getenv('UNSOLVED_DB_PATH', str(BASE_DIR / 'data' / 'cases.db'))).resolve()
LOG_PATH = Path(os.getenv('AGENT2_LOG_PATH', str(BASE_DIR / 'logs' / 'agent2.log'))).resolve()
CACHE_PATH = Path(os.getenv('AGENT2_CACHE_PATH', str(BASE_DIR / 'data' / 'agent2_v11_cache.json'))).resolve()

load_dotenv(AGENT1_DIR / '.env')

def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f'{name} phải là số nguyên, đang là: {raw!r}') from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f'{name} phải trong khoảng {minimum}..{maximum}, đang là {value}')
    return value

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('AGENT2_GEMINI_MODEL', os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')).strip()
REQUEST_TIMEOUT = _int('AGENT2_REQUEST_TIMEOUT', 45, 5, 180)
MAX_CASES_PER_RUN = _int('AGENT2_MAX_CASES', 5, 1, 100)
MAX_SOURCES_PER_CASE = _int('AGENT2_MAX_SOURCES', 8, 1, 30)
MIN_USABLE_SOURCES = _int('AGENT2_MIN_SOURCES', 1, 1, 10)
MIN_VERIFIED_SCORE = _int('AGENT2_MIN_SCORE', 65, 0, 100)
MIN_TEXT_LENGTH = _int('AGENT2_MIN_TEXT_LENGTH', 150, 50, 5000)
MIN_RELIABILITY = _int('AGENT2_MIN_RELIABILITY', 50, 0, 100)
MIN_RELEVANCE = _int('AGENT2_MIN_RELEVANCE', 2, 0, 20)
MAX_RETRIES = _int('AGENT2_MAX_RETRIES', 3, 1, 20)
SEARCH_CACHE_HOURS = _int('AGENT2_SEARCH_CACHE_HOURS', 24, 0, 720)
USER_AGENT = os.getenv('AGENT2_USER_AGENT', 'Mozilla/5.0 (compatible; UnsolvedCaseResearchBot/11.0)').strip()
BACKOFF_MINUTES = tuple(int(x.strip()) for x in os.getenv('AGENT2_BACKOFF_MINUTES', '5,30,120').split(',') if x.strip())
if not BACKOFF_MINUTES or any(x < 1 for x in BACKOFF_MINUTES):
    raise RuntimeError('AGENT2_BACKOFF_MINUTES phải gồm các số nguyên dương')

GEMINI_MAX_ATTEMPTS = _int('AGENT2_GEMINI_MAX_ATTEMPTS', 3, 1, 6)
GEMINI_RETRY_SECONDS = _int('AGENT2_GEMINI_RETRY_SECONDS', 2, 0, 30)
