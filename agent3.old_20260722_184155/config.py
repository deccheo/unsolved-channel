import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path("/opt/unsolved-channel")
AGENT1_DIR = BASE_DIR / "agent1"
DB_PATH = BASE_DIR / "data" / "cases.db"
LOG_PATH = BASE_DIR / "logs" / "agent3.log"
OUTPUT_DIR = BASE_DIR / "output" / "scripts"

load_dotenv(AGENT1_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()

MAX_CASES_PER_RUN = 3
TARGET_WORDS_MIN = 1500
TARGET_WORDS_MAX = 2200
