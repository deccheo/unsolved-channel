from pathlib import Path
import os

BASE_DIR = Path("/opt/unsolved-channel")
DB_PATH = BASE_DIR / "data" / "cases.db"
LOG_PATH = BASE_DIR / "logs" / "agent7.log"
OUTPUT_DIR = BASE_DIR / "output" / "videos"
TMP_DIR = BASE_DIR / "tmp" / "agent7"

WIDTH = int(os.getenv("AGENT7_WIDTH", "1920"))
HEIGHT = int(os.getenv("AGENT7_HEIGHT", "1080"))
FPS = int(os.getenv("AGENT7_FPS", "30"))
CRF = int(os.getenv("AGENT7_CRF", "23"))
PRESET = os.getenv("AGENT7_PRESET", "veryfast")
AUDIO_BITRATE = os.getenv("AGENT7_AUDIO_BITRATE", "192k")

MAX_CASES_PER_RUN = int(os.getenv("AGENT7_MAX_CASES", "1"))
MAX_WORKERS = max(1, int(os.getenv("AGENT7_MAX_WORKERS", "2")))
FFMPEG_RETRY_LIMIT = max(1, int(os.getenv("AGENT7_RETRY_LIMIT", "2")))
FFMPEG_RETRY_DELAY_SECONDS = max(1, int(os.getenv("AGENT7_RETRY_DELAY", "8")))
FFMPEG_TIMEOUT_SECONDS = max(60, int(os.getenv("AGENT7_FFMPEG_TIMEOUT", "1800")))
X264_THREADS_PER_JOB = max(1, int(os.getenv("AGENT7_X264_THREADS", "1")))

# Chế độ thử: chỉ ghép một số cảnh đầu. Production phải để False.
PREVIEW_MODE = os.getenv("AGENT7_PREVIEW_MODE", "0") == "1"
PREVIEW_SCENE_LIMIT = int(os.getenv("AGENT7_PREVIEW_SCENE_LIMIT", "3"))

# Giữ clip tạm khi render lỗi để lần sau tiếp tục; xóa sau khi video hoàn tất.
CLEAN_TEMP_AFTER_SUCCESS = os.getenv("AGENT7_CLEAN_TEMP", "1") == "1"
REUSE_VALID_CLIPS = os.getenv("AGENT7_REUSE_CLIPS", "1") == "1"
