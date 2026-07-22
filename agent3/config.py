from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(os.getenv("UNSOLVED_BASE_DIR", "/opt/unsolved-channel")).resolve()
AGENT1_ENV = BASE_DIR / "agent1" / ".env"

def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
        return
    except Exception:
        pass

    # Minimal fallback parser so Agent 3 does not depend on importing Agent 1
    # and can still start before optional dependencies are installed.
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)

_load_env_file(AGENT1_ENV)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()

DB_PATH = Path(
    os.getenv("UNSOLVED_DB_PATH", str(BASE_DIR / "data" / "cases.db"))
).resolve()
LOG_PATH = Path(
    os.getenv("AGENT3_LOG_PATH", str(BASE_DIR / "logs" / "agent3.log"))
).resolve()
OUTPUT_DIR = Path(
    os.getenv("AGENT3_OUTPUT_DIR", str(BASE_DIR / "output" / "scripts"))
).resolve()

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
