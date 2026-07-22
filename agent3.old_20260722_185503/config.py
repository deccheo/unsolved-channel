from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path("/opt/unsolved-channel")
A1_DIR = BASE_DIR / "agent1"
if str(A1_DIR) not in sys.path:
    sys.path.insert(0, str(A1_DIR))

try:
    from config import GEMINI_API_KEY, GEMINI_MODEL
except Exception:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

DB_PATH = Path(os.getenv("UNSOLVED_DB_PATH", str(BASE_DIR / "data" / "cases.db")))
LOG_PATH = Path(os.getenv("AGENT3_LOG_PATH", str(BASE_DIR / "logs" / "agent3.log")))
OUTPUT_DIR = Path(os.getenv("AGENT3_OUTPUT_DIR", str(BASE_DIR / "output" / "scripts")))

MAX_CASES_PER_RUN = int(os.getenv("AGENT3_MAX_CASES_PER_RUN", "4"))
TARGET_WORDS_MIN = int(os.getenv("AGENT3_TARGET_WORDS_MIN", "1500"))
TARGET_WORDS_MAX = int(os.getenv("AGENT3_TARGET_WORDS_MAX", "2100"))
MIN_SOURCE_COUNT = int(os.getenv("AGENT3_MIN_SOURCE_COUNT", "1"))
MIN_SOURCE_TEXT_CHARS = int(os.getenv("AGENT3_MIN_SOURCE_TEXT_CHARS", "150"))
MIN_QA_SCORE = int(os.getenv("AGENT3_MIN_QA_SCORE", "95"))
MAX_REWRITES = int(os.getenv("AGENT3_MAX_REWRITES", "1"))
MAX_SCRIPT_RETRIES = int(os.getenv("AGENT3_MAX_SCRIPT_RETRIES", "3"))

if TARGET_WORDS_MIN < 500 or TARGET_WORDS_MAX <= TARGET_WORDS_MIN:
    raise RuntimeError("Cấu hình độ dài kịch bản không hợp lệ")
if not 0 <= MIN_QA_SCORE <= 100:
    raise RuntimeError("AGENT3_MIN_QA_SCORE phải nằm trong 0..100")
