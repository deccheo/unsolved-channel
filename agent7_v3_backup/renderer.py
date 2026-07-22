import json
import subprocess
import time
from pathlib import Path

from config import (
    WIDTH,
    HEIGHT,
    FPS,
    CRF,
    PRESET,
    AUDIO_BITRATE,
    FFMPEG_RETRY_LIMIT,
    FFMPEG_RETRY_DELAY_SECONDS,
    FFMPEG_TIMEOUT_SECONDS,
    X264_THREADS_PER_JOB,
    REUSE_VALID_CLIPS,
)

RETRYABLE_TEXT = (
    "resource temporarily unavailable",
    "temporarily unavailable",
    "connection reset",
    "connection timed out",
    "timeout",
    "input/output error",
    "device or resource busy",
    "cannot allocate memory",
)


def _run_once(cmd: list[str]) -> None:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-7000:] or f"Lệnh lỗi: {cmd[0]}")


def run_command(cmd: list[str]) -> int:
    """Chạy FFmpeg/ffprobe có retry; trả về số lần retry thực tế."""
    retries = 0
    for attempt in range(1, FFMPEG_RETRY_LIMIT + 1):
        try:
            _run_once(cmd)
            return retries
        except (subprocess.TimeoutExpired, OSError, RuntimeError) as exc:
            text = str(exc).lower()
            transient = isinstance(exc, (subprocess.TimeoutExpired, OSError)) or any(
                marker in text for marker in RETRYABLE_TEXT
            )
            if not transient or attempt >= FFMPEG_RETRY_LIMIT:
                raise
            retries += 1
            time.sleep(FFMPEG_RETRY_DELAY_SECONDS * attempt)
    return retries


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=True,
    )
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    if duration <= 0:
        raise RuntimeError(f"Thời lượng không hợp lệ: {path}")
    return duration


def probe_streams(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,width,height",
            "-show_entries", "format=duration,size",
            "-of", "json", str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(result.stdout)


def validate_video(path: Path, expected_duration: float | None = None) -> float:
    if not path.is_file() or path.stat().st_size < 100_000:
        raise RuntimeError(f"Video không tồn tại hoặc quá nhỏ: {path}")
    data = probe_streams(path)
    streams = data.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams):
        raise RuntimeError(f"Video không có luồng hình: {path}")
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise RuntimeError(f"Video không có luồng tiếng: {path}")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError(f"Video có thời lượng không hợp lệ: {path}")
    if expected_duration and abs(duration - expected_duration) > max(1.0, expected_duration * 0.04):
        raise RuntimeError(
            f"Sai thời lượng: {path} | thực tế={duration:.2f}s | dự kiến={expected_duration:.2f}s"
        )
    return duration


def reusable_clip(output_path: Path, image_path: Path, audio_path: Path, duration: float) -> bool:
    if not REUSE_VALID_CLIPS or not output_path.is_file():
        return False
    try:
        newest_input = max(image_path.stat().st_mtime, audio_path.stat().st_mtime)
        if output_path.stat().st_mtime < newest_input:
            return False
        validate_video(output_path, duration)
        return True
    except Exception:
        return False


def make_scene_clip(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    scene_no: int,
) -> dict:
    if not image_path.is_file():
        raise FileNotFoundError(f"Không thấy ảnh: {image_path}")
    if not audio_path.is_file():
        raise FileNotFoundError(f"Không thấy audio: {audio_path}")

    duration = probe_duration(audio_path)
    if reusable_clip(output_path, image_path, audio_path, duration):
        return {"duration": duration, "reused": True, "retries": 0}

    total_frames = max(1, round(duration * FPS))
    zoom_expression = (
        "min(zoom+0.0007,1.10)"
        if scene_no % 2
        else "if(lte(on,1),1.10,max(1.0,zoom-0.0007))"
    )
    video_filter = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"zoompan=z='{zoom_expression}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        "format=yuv420p,"
        "fade=t=in:st=0:d=0.30,"
        f"fade=t=out:st={max(0.0, duration - 0.30):.3f}:d=0.30"
    )
    audio_filter = (
        "afade=t=in:st=0:d=0.10,"
        f"afade=t=out:st={max(0.0, duration - 0.15):.3f}:d=0.15"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".rendering.mp4")
    temp_path.unlink(missing_ok=True)

    retries = run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", str(FPS), "-i", str(image_path),
        "-i", str(audio_path),
        "-vf", video_filter,
        "-af", audio_filter,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-threads", str(X264_THREADS_PER_JOB),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart",
        str(temp_path),
    ])
    validate_video(temp_path, duration)
    temp_path.replace(output_path)
    return {"duration": duration, "reused": False, "retries": retries}


def concat_clips(clips: list[Path], output_path: Path, expected_duration: float) -> int:
    if not clips:
        raise RuntimeError("Không có clip để ghép")
    for clip in clips:
        if not clip.is_file():
            raise FileNotFoundError(f"Thiếu clip tạm: {clip}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_file = output_path.parent / f".{output_path.stem}.concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{clip.as_posix()}'" for clip in clips),
        encoding="utf-8",
    )
    temp_path = output_path.with_suffix(".uploading.mp4")
    temp_path.unlink(missing_ok=True)
    try:
        retries = run_command([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", "-movflags", "+faststart", str(temp_path),
        ])
        validate_video(temp_path, expected_duration)
        temp_path.replace(output_path)
        return retries
    finally:
        concat_file.unlink(missing_ok=True)
        temp_path.unlink(missing_ok=True)
