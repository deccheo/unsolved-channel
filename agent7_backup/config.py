from pathlib import Path

BASE_DIR = Path("/opt/unsolved-channel")
DB_PATH = BASE_DIR / "data" / "cases.db"
LOG_PATH = BASE_DIR / "logs" / "agent7.log"
OUTPUT_DIR = BASE_DIR / "output" / "videos"
TMP_DIR = BASE_DIR / "tmp" / "agent7"

WIDTH = 1920
HEIGHT = 1080
FPS = 30
CRF = 23
PRESET = "veryfast"

MAX_CASES_PER_RUN = 1

# Chế độ thử: chỉ ghép tối đa 3 cảnh có đủ cả ảnh và giọng.
PREVIEW_MODE = False
PREVIEW_SCENE_LIMIT = 0
