import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path("/opt/unsolved-channel")
AGENT1_DIR = BASE_DIR / "agent1"
DB_PATH = BASE_DIR / "data" / "cases.db"
LOG_PATH = BASE_DIR / "logs" / "agent8.log"
OUTPUT_DIR = BASE_DIR / "output" / "thumbnails"
TMP_DIR = BASE_DIR / "tmp" / "agent8"

load_dotenv(AGENT1_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
IMAGE_MODEL = os.getenv(
    "GEMINI_IMAGE_MODEL",
    "gemini-3.1-flash-image",
).strip()

WIDTH = 1280
HEIGHT = 720
MAX_CASES_PER_RUN = 1
RETRY_LIMIT = 3
RETRY_DELAY_SECONDS = 8
