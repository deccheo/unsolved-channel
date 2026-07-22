import logging
import re
import shutil
import sys
from pathlib import Path

from config import (
    LOG_PATH,
    OUTPUT_DIR,
    TMP_DIR,
    MAX_CASES_PER_RUN,
    PREVIEW_MODE,
    PREVIEW_SCENE_LIMIT,
)
from database import (
    migrate,
    candidate_cases,
    ready_scenes,
    total_scene_count,
    save_video,
    mark_retry,
)
from renderer import make_scene_clip, concat_clips, probe_duration


def setup_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def slugify(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "case"


def case_title(case) -> str:
    keys = set(case.keys())

    for field in ("script_title", "case_name", "title"):
        if field in keys and case[field]:
            return str(case[field])

    return f"case-{case['id']}"


def run():
    setup_logging()
    migrate()

    cases = candidate_cases(MAX_CASES_PER_RUN)
    logging.info("Agent 7 bắt đầu: %s hồ sơ", len(cases))

    for case in cases:
        title = case_title(case)
        ready = list(ready_scenes(case["id"]))
        total = total_scene_count(case["id"])

        if not ready:
            logging.warning("Không có cảnh đủ ảnh và giọng: %s", title)
            continue

        selected = ready[:PREVIEW_SCENE_LIMIT] if PREVIEW_MODE else ready

        work_dir = TMP_DIR / f"{case['id']:04d}"
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        mode = "preview" if PREVIEW_MODE else "full"
        output_path = OUTPUT_DIR / (
            f"{case['id']:04d}-{slugify(title)}-{mode}.mp4"
        )

        logging.info(
            "Render: %s | %s/%s cảnh đủ điều kiện",
            title,
            len(selected),
            total,
        )

        try:
            clips = []

            for index, scene in enumerate(selected, 1):
                clip_path = work_dir / f"scene_{scene['scene_no']:03d}.mp4"

                duration = make_scene_clip(
                    Path(scene["image_path"]),
                    Path(scene["audio_path"]),
                    clip_path,
                    int(scene["scene_no"]),
                )

                clips.append(clip_path)

                logging.info(
                    "[%s/%s] Cảnh %s | %.1f giây",
                    index,
                    len(selected),
                    scene["scene_no"],
                    duration,
                )

            concat_clips(clips, output_path)
            final_duration = probe_duration(output_path)

            complete = (
                not PREVIEW_MODE
                and len(selected) == total
            )

            save_video(
                case_id=case["id"],
                path=str(output_path),
                duration=final_duration,
                scene_count=len(selected),
                complete=complete,
            )

            logging.info(
                "Đã tạo video: %s | %.1f giây",
                output_path,
                final_duration,
            )

        except Exception as exc:
            logging.exception("Lỗi render: %s", title)
            mark_retry(case["id"], str(exc))

    logging.info("Agent 7 hoàn thành")


if __name__ == "__main__":
    run()
