import json
import math
import re
import subprocess
from pathlib import Path

from config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    FPS,
    VIDEO_CRF,
    VIDEO_PRESET,
    AUDIO_BITRATE,
)

def run_cmd(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-5000:])

def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())

def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def write_srt(scenes, output: Path) -> float:
    current = 0.0
    lines = []

    for index, scene in enumerate(scenes, start=1):
        audio = Path(scene["audio_path"])
        duration = float(scene["audio_duration"] or 0)
        if duration <= 0:
            duration = probe_duration(audio)

        start = current
        end = current + duration
        narration = re.sub(r"\s+", " ", scene["narration"]).strip()

        lines.extend([
            str(index),
            f"{srt_time(start)} --> {srt_time(end)}",
            narration,
            "",
        ])
        current = end

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return current

def render_scene(scene, output: Path) -> float:
    image = Path(scene["image_path"])
    audio = Path(scene["audio_path"])
    duration = float(scene["audio_duration"] or 0)

    if duration <= 0:
        duration = probe_duration(audio)

    frames = max(1, math.ceil(duration * FPS))

    vf = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
        f"zoompan=z='min(zoom+0.00035,1.08)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={FPS},"
        "format=yuv420p"
    )

    run_cmd([
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image),
        "-i", str(audio),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-r", str(FPS),
        "-c:v", "libx264",
        "-preset", VIDEO_PRESET,
        "-crf", str(VIDEO_CRF),
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-shortest",
        str(output),
    ])
    return duration

def concat_scenes(parts: list[Path], output: Path) -> None:
    list_file = output.with_suffix(".concat.txt")
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts),
        encoding="utf-8",
    )

    run_cmd([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output),
    ])

def burn_subtitles(video: Path, srt: Path, output: Path) -> None:
    subtitle_filter = (
        f"subtitles={srt.as_posix()}:"
        "force_style='FontName=DejaVu Sans,"
        "FontSize=19,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Shadow=1,"
        "MarginV=45,"
        "Alignment=2'"
    )

    run_cmd([
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", subtitle_filter,
        "-c:v", "libx264",
        "-preset", VIDEO_PRESET,
        "-crf", str(VIDEO_CRF),
        "-c:a", "copy",
        str(output),
    ])

def render_case(case, scenes, work_dir: Path, final_video: Path, subtitle_path: Path) -> float:
    work_dir.mkdir(parents=True, exist_ok=True)
    parts = []

    total = write_srt(scenes, subtitle_path)

    for scene in scenes:
        part = work_dir / f"scene_{scene['scene_no']:03d}.mp4"
        render_scene(scene, part)
        parts.append(part)

    merged = work_dir / "merged.mp4"
    concat_scenes(parts, merged)
    burn_subtitles(merged, subtitle_path, final_video)

    manifest = {
        "case_id": case["id"],
        "title": case["script_title"] or case["case_name"] or case["title"],
        "duration_seconds": total,
        "scene_count": len(scenes),
        "video_path": str(final_video),
        "subtitle_path": str(subtitle_path),
    }

    (work_dir / "render_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return total
