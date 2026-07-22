from pathlib import Path
import os

BASE_DIR = Path('/opt/unsolved-channel')
AGENT_DIR = BASE_DIR / 'agent9'
OUTPUT_DIR = BASE_DIR / 'output'
METADATA_DIR = OUTPUT_DIR / 'metadata'
TITLE_DIR = OUTPUT_DIR / 'titles'
DESCRIPTION_DIR = OUTPUT_DIR / 'descriptions'
TAG_DIR = OUTPUT_DIR / 'tags'
LOG_DIR = AGENT_DIR / 'logs'
STATE_FILE = AGENT_DIR / 'state.json'

DEFAULT_MODEL = 'gemini-3.1-flash-lite'
GEMINI_MODEL = os.getenv('AGENT9_GEMINI_MODEL', os.getenv('GEMINI_MODEL', DEFAULT_MODEL))
MAX_ITEMS_PER_RUN = max(1, int(os.getenv('AGENT9_MAX_ITEMS', '3')))
RETRY_LIMIT = max(1, int(os.getenv('AGENT9_RETRY_LIMIT', '3')))
RETRY_DELAY_SECONDS = max(1, int(os.getenv('AGENT9_RETRY_DELAY_SECONDS', '5')))
REQUEST_TIMEOUT_SECONDS = max(30, int(os.getenv('AGENT9_TIMEOUT_SECONDS', '180')))
MAX_SOURCE_CHARS = max(4000, int(os.getenv('AGENT9_MAX_SOURCE_CHARS', '14000')))
DEFAULT_PRIVACY = os.getenv('AGENT9_DEFAULT_PRIVACY', 'public').strip().lower()
DEFAULT_LANGUAGE = os.getenv('AGENT9_DEFAULT_LANGUAGE', 'en').strip() or 'en'
DEFAULT_CATEGORY_ID = os.getenv('AGENT9_CATEGORY_ID', '24').strip() or '24'

for folder in (METADATA_DIR, TITLE_DIR, DESCRIPTION_DIR, TAG_DIR, LOG_DIR):
    folder.mkdir(parents=True, exist_ok=True)
