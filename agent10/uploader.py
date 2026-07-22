import json
import logging
import mimetypes
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config import (
    DEFAULT_CATEGORY_ID,
    DEFAULT_LANGUAGE,
    DEFAULT_PRIVACY,
    PLAYLIST_DESCRIPTION,
    PLAYLIST_TITLE,
    SCOPES,
    THUMBNAILS_DIR,
    TOKEN_FILE,
    MAX_RETRIES,
    RETRY_BASE_SECONDS,
    UPLOAD_CHUNK_MB,
)

log = logging.getLogger("agent10")

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


def retry_call(name: str, func: Callable[[], Any]) -> Any:
    delay = RETRY_BASE_SECONDS
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
                raise
            log.warning(
                "%s lỗi HTTP %s, thử lại %s/%s sau %ss",
                name, status, attempt, MAX_RETRIES, delay
            )
        except (OSError, TimeoutError) as exc:
            if attempt == MAX_RETRIES:
                raise
            log.warning(
                "%s lỗi mạng %s, thử lại %s/%s sau %ss",
                name, exc, attempt, MAX_RETRIES, delay
            )
        time.sleep(delay)
        delay = min(delay * 2, 60)


def load_credentials() -> Credentials:
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            "Chưa có token YouTube. Hãy chạy auth_youtube.py để xác thực."
        )

    credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if credentials.expired and credentials.refresh_token:
        retry_call("Làm mới token", lambda: credentials.refresh(Request()))
        TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
        TOKEN_FILE.chmod(0o600)

    if not credentials.valid:
        raise RuntimeError("Token YouTube không hợp lệ. Hãy xác thực lại.")
    return credentials


def youtube_client():
    return build("youtube", "v3", credentials=load_credentials(), cache_discovery=False)


def normalize_tags(tags: Any) -> list[str]:
    if isinstance(tags, str):
        tags = [part.strip() for part in tags.split(",")]
    if not isinstance(tags, list):
        return []

    result: list[str] = []
    total = 0
    for item in tags:
        tag = re.sub(r"\s+", " ", str(item)).strip()
        if not tag or tag in result:
            continue
        if total + len(tag) > 450:
            break
        result.append(tag)
        total += len(tag)
    return result[:30]


def video_base_slug(video_path: Path) -> str:
    stem = video_path.stem
    for suffix in ("-preview", "_preview", "-video", "_video"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def find_thumbnail(video_path: Path) -> Path | None:
    slug = video_base_slug(video_path)
    candidate_names = [
        f"{slug}-thumbnail.jpg",
        f"{slug}-thumbnail.jpeg",
        f"{slug}-thumbnail.png",
        f"{slug}.jpg",
        f"{slug}.jpeg",
        f"{slug}.png",
        f"{video_path.stem}-thumbnail.jpg",
        f"{video_path.stem}.jpg",
    ]
    for name in candidate_names:
        path = THUMBNAILS_DIR / name
        if path.exists():
            return path

    for path in sorted(THUMBNAILS_DIR.rglob("*")):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        if slug in path.stem:
            return path
    return None


def get_or_create_playlist(youtube) -> str:
    request = youtube.playlists().list(
        part="snippet,status",
        mine=True,
        maxResults=50,
    )

    while request is not None:
        response = retry_call("Tìm playlist", request.execute)
        for item in response.get("items", []):
            if item.get("snippet", {}).get("title", "").strip() == PLAYLIST_TITLE:
                return item["id"]
        request = youtube.playlists().list_next(request, response)

    response = retry_call(
        "Tạo playlist",
        lambda: youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": PLAYLIST_TITLE,
                    "description": PLAYLIST_DESCRIPTION,
                    "defaultLanguage": DEFAULT_LANGUAGE,
                },
                "status": {"privacyStatus": "public"},
            },
        ).execute(),
    )
    playlist_id = response["id"]
    log.info("Đã tạo playlist: %s", PLAYLIST_TITLE)
    return playlist_id


def add_to_playlist(youtube, video_id: str) -> str:
    playlist_id = get_or_create_playlist(youtube)
    retry_call(
        "Thêm vào playlist",
        lambda: youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
        ).execute(),
    )
    log.info("Đã thêm video vào playlist: %s", PLAYLIST_TITLE)
    return playlist_id


def set_thumbnail(youtube, video_id: str, video_path: Path) -> Path | None:
    thumbnail_path = find_thumbnail(video_path)
    if not thumbnail_path:
        log.warning("Không tìm thấy thumbnail cho %s", video_path.name)
        return None

    retry_call(
        "Đặt thumbnail",
        lambda: youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path)),
        ).execute(),
    )
    log.info("Đã đặt thumbnail: %s", thumbnail_path)
    return thumbnail_path


def upload_video(video_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    youtube = youtube_client()

    title = str(metadata.get("title") or video_path.stem)[:100]
    description = str(metadata.get("description") or "")[:5000]
    tags = normalize_tags(metadata.get("tags"))
    category_id = str(
        metadata.get("categoryId")
        or metadata.get("category")
        or DEFAULT_CATEGORY_ID
    )
    privacy = str(metadata.get("privacyStatus") or DEFAULT_PRIVACY).lower()
    language = str(metadata.get("defaultLanguage") or DEFAULT_LANGUAGE)
    made_for_kids = bool(metadata.get("madeForKids", False))

    if privacy not in {"public", "private", "unlisted"}:
        privacy = DEFAULT_PRIVACY

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
            "embeddable": True,
            "publicStatsViewable": True,
        },
    }

    def do_upload():
        media = MediaFileUpload(
            str(video_path),
            mimetype=mimetypes.guess_type(video_path.name)[0] or "video/mp4",
            resumable=True,
            chunksize=UPLOAD_CHUNK_MB * 1024 * 1024,
        )
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info("Upload %.1f%%", status.progress() * 100)
        return response

    response = retry_call("Upload video", do_upload)
    video_id = response["id"]

    thumbnail_path = set_thumbnail(youtube, video_id, video_path)
    playlist_id = add_to_playlist(youtube, video_id)

    return {
        "video_id": video_id,
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        "title": title,
        "privacyStatus": privacy,
        "categoryId": category_id,
        "defaultLanguage": language,
        "tags": tags,
        "playlistId": playlist_id,
        "playlistTitle": PLAYLIST_TITLE,
        "video_file": str(video_path),
        "thumbnail_file": str(thumbnail_path) if thumbnail_path else None,
    }
