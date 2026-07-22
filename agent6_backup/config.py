import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path("/opt/unsolved-channel")
AGENT1_DIR = BASE_DIR / "agent1"
DB_PATH = BASE_DIR / "data" / "cases.db"
LOG_PATH = BASE_DIR / "logs" / "agent6.log"
OUTPUT_DIR = BASE_DIR / "output" / "audio"

load_dotenv(AGENT1_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TTS_MODEL = os.getenv(
    "GEMINI_TTS_MODEL",
    "gemini-3.1-flash-tts-preview",
).strip()
TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Charon").strip()

MAX_CASES_PER_RUN = 1
MAX_CLIPS_PER_RUN = 3
RETRY_LIMIT = 3
RETRY_DELAY_SECONDS = 8

SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2
