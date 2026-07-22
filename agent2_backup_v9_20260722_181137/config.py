import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path('/opt/unsolved-channel')
AGENT1_DIR = BASE_DIR / 'agent1'
DB_PATH = BASE_DIR / 'data' / 'cases.db'
LOG_PATH = BASE_DIR / 'logs' / 'agent2.log'
OUTPUT_DIR = BASE_DIR / 'output'
CACHE_PATH = BASE_DIR / 'data' / 'agent2_v7_cache.json'

load_dotenv(AGENT1_DIR / '.env')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('AGENT2_GEMINI_MODEL', os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite')).strip()
REQUEST_TIMEOUT = int(os.getenv('AGENT2_REQUEST_TIMEOUT', '45'))
USER_AGENT = os.getenv('AGENT2_USER_AGENT', 'Mozilla/5.0 (compatible; UnsolvedCaseResearchBot/7.0)')
MAX_CASES_PER_RUN = int(os.getenv('AGENT2_MAX_CASES', '5'))
MAX_SOURCES_PER_CASE = int(os.getenv('AGENT2_MAX_SOURCES', '8'))
MIN_USABLE_SOURCES = int(os.getenv('AGENT2_MIN_SOURCES', '1'))
MIN_VERIFIED_SCORE = int(os.getenv('AGENT2_MIN_SCORE', '40'))
MAX_RETRIES = int(os.getenv('AGENT2_MAX_RETRIES', '3'))
SEARCH_CACHE_HOURS = int(os.getenv('AGENT2_SEARCH_CACHE_HOURS', '24'))
BACKOFF_MINUTES = tuple(int(x.strip()) for x in os.getenv('AGENT2_BACKOFF_MINUTES', '5,30,120').split(',') if x.strip())
