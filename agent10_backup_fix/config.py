from pathlib import Path
import os

BASE_DIR = Path(os.getenv("UNSOLVED_BASE_DIR", "/opt/unsolved-channel"))
AGENT_DIR = BASE_DIR / "agent10"
OUTPUT_DIR = BASE_DIR / "output"
VIDEOS_DIR = OUTPUT_DIR / "videos"
THUMBNAILS_DIR = OUTPUT_DIR / "thumbnails"
METADATA_DIR = OUTPUT_DIR / "metadata"
UPLOADED_DIR = OUTPUT_DIR / "uploaded"
SECRETS_DIR = BASE_DIR / "secrets"

CLIENT_SECRET_FILE = SECRETS_DIR / "client_secret.json"
TOKEN_FILE = SECRETS_DIR / "youtube_token.json"
STATE_FILE = AGENT_DIR / "state.json"
DAILY_STATE_FILE = AGENT_DIR / "daily_state.json"
LOCK_FILE = AGENT_DIR / "agent10.lock"
LOG_FILE = AGENT_DIR / "logs" / "agent10.log"

DEFAULT_PRIVACY = os.getenv("YOUTUBE_PRIVACY", "public").strip().lower()
DEFAULT_CATEGORY_ID = os.getenv("YOUTUBE_CATEGORY_ID", "24").strip()
DEFAULT_LANGUAGE = os.getenv("YOUTUBE_LANGUAGE", "en").strip()
PLAYLIST_TITLE = os.getenv("YOUTUBE_PLAYLIST_TITLE", "Unsolved Mysteries").strip()
PLAYLIST_DESCRIPTION = os.getenv(
    "YOUTUBE_PLAYLIST_DESCRIPTION",
    "Unsolved mysteries and documentary storytelling.",
).strip()

MAX_UPLOADS_PER_RUN = max(1, int(os.getenv("AGENT10_MAX_UPLOADS", "1")))
DAILY_LIMIT = max(1, int(os.getenv("AGENT10_DAILY_LIMIT", "4")))
MIN_VIDEO_SECONDS = max(1.0, float(os.getenv("AGENT10_MIN_VIDEO_SECONDS", "20")))
MIN_VIDEO_BYTES = max(1, int(os.getenv("AGENT10_MIN_VIDEO_BYTES", "1000000")))
ALLOW_PREVIEW = os.getenv("AGENT10_ALLOW_PREVIEW", "0") == "1"
ALLOW_PARTS = os.getenv("AGENT10_ALLOW_PARTS", "0") == "1"
REQUIRE_AUDIO = os.getenv("AGENT10_REQUIRE_AUDIO", "1") == "1"
REQUIRE_THUMBNAIL = os.getenv("AGENT10_REQUIRE_THUMBNAIL", "1") == "1"
REQUIRE_PUBLIC = os.getenv("AGENT10_REQUIRE_PUBLIC", "1") == "1"

DRIVE_ENABLED = os.getenv("AGENT10_DRIVE_ENABLED", "1") == "1"
DRIVE_REMOTE = os.getenv("AGENT10_DRIVE_REMOTE", "gdrive").strip()
DRIVE_FOLDER = os.getenv("AGENT10_DRIVE_FOLDER", "UnsolvedChannel/YouTubeArchive").strip("/")
DELETE_LOCAL_AFTER_DRIVE = os.getenv("AGENT10_DELETE_LOCAL_AFTER_DRIVE", "1") == "1"
LOW_DISK_PERCENT = max(1, min(99, int(os.getenv("AGENT10_LOW_DISK_PERCENT", "15"))))

UPLOAD_CHUNK_MB = max(1, int(os.getenv("AGENT10_UPLOAD_CHUNK_MB", "8")))
MAX_RETRIES = max(1, int(os.getenv("AGENT10_MAX_RETRIES", "5")))
RETRY_BASE_SECONDS = max(1, int(os.getenv("AGENT10_RETRY_BASE_SECONDS", "5")))

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
