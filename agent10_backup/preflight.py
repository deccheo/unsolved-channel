import json
import re
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from config import (
    ALLOW_PREVIEW,
    MIN_VIDEO_BYTES,
    MIN_VIDEO_SECONDS,
    REQUIRE_AUDIO,
    REQUIRE_THUMBNAIL,
    THUMBNAILS_DIR,
)


def base_slug(video: Path) -> str:
    stem = video.stem
    for suffix in ("-preview", "_preview", "-final", "_final", "-video", "_video"):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
    return stem


def story_id(path: Path) -> str:
    match = re.match(r"^(\d{4,})", path.stem)
    return match.group(1) if match else base_slug(path)


def find_thumbnail(video: Path) -> Path | None:
    sid = story_id(video)
    slug = base_slug(video)
    candidates = []
    for path in THUMBNAILS_DIR.rglob("*"):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        if path.stem.startswith(sid) or slug in path.stem:
            candidates.append(path)
    return sorted(candidates)[0] if candidates else None


def ffprobe(video: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error",
        "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height",
        "-of", "json", str(video),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=60, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe thất bại")
    return json.loads(result.stdout)


def validate_metadata(metadata: dict[str, Any]) -> list[str]:
    errors = []
    title = str(metadata.get("title") or "").strip()
    description = str(metadata.get("description") or "")
    tags = metadata.get("tags") or []

    if not title:
        errors.append("thiếu tiêu đề")
    elif len(title) > 100:
        errors.append("tiêu đề dài hơn 100 ký tự")

    if len(description) > 5000:
        errors.append("mô tả dài hơn 5000 ký tự")

    if isinstance(tags, str):
        tags = [x.strip() for x in tags.split(",")]
    if sum(len(str(x)) for x in tags) > 450:
        errors.append("tổng độ dài tags vượt 450 ký tự")
    return errors


def validate(video: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    errors = []

    if not ALLOW_PREVIEW and "preview" in video.stem.lower():
        errors.append("file preview bị chặn")

    if not video.exists():
        errors.append("video không tồn tại")
    elif video.stat().st_size < MIN_VIDEO_BYTES:
        errors.append(f"video nhỏ hơn {MIN_VIDEO_BYTES} byte")

    info = {}
    if not errors or video.exists():
        try:
            info = ffprobe(video)
            duration = float(info.get("format", {}).get("duration") or 0)
            streams = info.get("streams", [])
            has_video = any(x.get("codec_type") == "video" for x in streams)
            has_audio = any(x.get("codec_type") == "audio" for x in streams)

            if duration < MIN_VIDEO_SECONDS:
                errors.append(f"video ngắn hơn {MIN_VIDEO_SECONDS} giây")
            if not has_video:
                errors.append("không có luồng hình")
            if REQUIRE_AUDIO and not has_audio:
                errors.append("không có luồng âm thanh")
        except Exception as exc:
            errors.append(f"ffprobe lỗi: {exc}")

    errors.extend(validate_metadata(metadata))

    thumbnail = find_thumbnail(video)
    if REQUIRE_THUMBNAIL and thumbnail is None:
        errors.append("thiếu thumbnail")

    thumb_info = None
    if thumbnail:
        try:
            if thumbnail.stat().st_size > 2 * 1024 * 1024:
                errors.append("thumbnail lớn hơn 2 MB")
            with Image.open(thumbnail) as image:
                width, height = image.size
                ratio = width / height if height else 0
                thumb_info = {"width": width, "height": height}
                if abs(ratio - 16 / 9) > 0.08:
                    errors.append("thumbnail không đúng tỷ lệ 16:9")
        except Exception as exc:
            errors.append(f"thumbnail lỗi: {exc}")

    return {
        "ok": not errors,
        "errors": errors,
        "video_info": info,
        "thumbnail": str(thumbnail) if thumbnail else None,
        "thumbnail_info": thumb_info,
        "story_id": story_id(video),
    }
