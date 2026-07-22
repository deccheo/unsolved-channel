from pathlib import Path
import os

BASE_DIR = Path("/opt/unsolved-channel")
AGENT_DIR = BASE_DIR / "agent9"
OUTPUT_DIR = BASE_DIR / "output"
METADATA_DIR = OUTPUT_DIR / "metadata"
TITLE_DIR = OUTPUT_DIR / "titles"
DESCRIPTION_DIR = OUTPUT_DIR / "descriptions"
TAG_DIR = OUTPUT_DIR / "tags"
STATE_FILE = AGENT_DIR / "state.json"

DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
MAX_ITEMS_PER_RUN = int(os.getenv("AGENT9_MAX_ITEMS", "3"))

for folder in (METADATA_DIR, TITLE_DIR, DESCRIPTION_DIR, TAG_DIR):
    folder.mkdir(parents=True, exist_ok=True)
