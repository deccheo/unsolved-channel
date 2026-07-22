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
    os.getenv("AGENT4_LOG_PATH", str(BASE_DIR / "logs" / "agent4.log"))
).resolve()
OUTPUT_DIR = Path(
    os.getenv("AGENT4_OUTPUT_DIR", str(BASE_DIR / "output" / "scenes"))
).resolve()

MAX_CASES_PER_RUN = int(os.getenv("AGENT4_MAX_CASES_PER_RUN", "2"))
MAX_RETRIES = int(os.getenv("AGENT4_MAX_RETRIES", "3"))
MIN_SCENE_WORDS = int(os.getenv("AGENT4_MIN_SCENE_WORDS", "18"))
TARGET_SCENE_WORDS = int(os.getenv("AGENT4_TARGET_SCENE_WORDS", "32"))
MAX_SCENE_WORDS = int(os.getenv("AGENT4_MAX_SCENE_WORDS", "52"))
MIN_SCENES = int(os.getenv("AGENT4_MIN_SCENES", "8"))
MAX_SCENES = int(os.getenv("AGENT4_MAX_SCENES", "90"))
MIN_QA_SCORE = int(os.getenv("AGENT4_MIN_QA_SCORE", "95"))
MAX_REWRITES = int(os.getenv("AGENT4_MAX_REWRITES", "1"))
PROMPT_VERSION = os.getenv("AGENT4_PROMPT_VERSION", "documentary-v2").strip()

if not (8 <= MIN_SCENE_WORDS < TARGET_SCENE_WORDS < MAX_SCENE_WORDS <= 90):
    raise RuntimeError("Cấu hình số từ mỗi cảnh không hợp lệ")
if not (1 <= MIN_SCENES < MAX_SCENES <= 200):
    raise RuntimeError("Cấu hình số cảnh không hợp lệ")
if not 0 <= MIN_QA_SCORE <= 100:
    raise RuntimeError("AGENT4_MIN_QA_SCORE phải nằm trong 0..100")
