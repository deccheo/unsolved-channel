import json
import subprocess
from pathlib import Path

from config import WIDTH, HEIGHT, FPS, CRF, PRESET


def run_command(cmd: list[str]) -> None:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-7000:])


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
        check=True,
    )

    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])

    if duration <= 0:
        raise RuntimeError(f"Thời lượng không hợp lệ: {path}")

    return duration


def make_scene_clip(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    scene_no: int,
) -> float:
    if not image_path.is_file():
        raise FileNotFoundError(f"Không thấy ảnh: {image_path}")

    if not audio_path.is_file():
        raise FileNotFoundError(f"Không thấy audio: {audio_path}")

    duration = probe_duration(audio_path)
    total_frames = max(1, round(duration * FPS))

    if scene_no % 2:
        zoom_expression = "min(zoom+0.0007,1.10)"
    else:
        zoom_expression = "if(lte(on,1),1.10,max(1.0,zoom-0.0007))"

    video_filter = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"zoompan="
        f"z='{zoom_expression}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:"
        f"s={WIDTH}x{HEIGHT}:"
        f"fps={FPS},"
        f"format=yuv420p,"
        f"fade=t=in:st=0:d=0.30,"
        f"fade=t=out:st={max(0.0, duration - 0.30):.3f}:d=0.30"
    )

    audio_filter = (
        "afade=t=in:st=0:d=0.10,"
        f"afade=t=out:st={max(0.0, duration - 0.15):.3f}:d=0.15"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    run_command([
        "ffmpeg",
        "-y",
        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(image_path),
        "-i", str(audio_path),
        "-vf", video_filter,
        "-af", audio_filter,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", PRESET,
        "-crf", str(CRF),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ])

    return duration


def concat_clips(clips: list[Path], output_path: Path) -> None:
    if not clips:
        raise RuntimeError("Không có clip để ghép")

    for clip in clips:
        if not clip.is_file():
            raise FileNotFoundError(f"Thiếu clip tạm: {clip}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_file = output_path.parent / "concat_agent7.txt"

    concat_file.write_text(
        "\n".join(f"file '{clip.as_posix()}'" for clip in clips),
        encoding="utf-8",
    )

    run_command([
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ])
