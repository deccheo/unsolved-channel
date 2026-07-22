import logging
import re
import sys
import time

from config import (
    LOG_PATH,
    OUTPUT_DIR,
    MAX_CASES_PER_RUN,
    MAX_CLIPS_PER_RUN,
    RETRY_LIMIT,
    RETRY_DELAY_SECONDS,
)
from database import (
    migrate,
    pending_cases,
    pending_scenes,
    mark_scene_ready,
    mark_scene_retry,
    finalize_case,
)
from tts import generate_voice

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
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "case"

def run():
    setup_logging()
    migrate()

    cases = pending_cases(MAX_CASES_PER_RUN)
    logging.info("Agent 6 bắt đầu: %s hồ sơ", len(cases))

    remaining = MAX_CLIPS_PER_RUN

    for case_index, case in enumerate(cases, 1):
        if remaining <= 0:
            break

        title = (
            case["script_title"]
            or case["case_name"]
            or case["title"]
        )
        folder = OUTPUT_DIR / (
            f"{case['id']:04d}-{slugify(title)}"
        )
        scenes = pending_scenes(case["id"], remaining)

        logging.info(
            "[%s/%s] Tạo giọng: %s | %s cảnh trong lần chạy này",
            case_index,
            len(cases),
            title,
            len(scenes),
        )

        for scene in scenes:
            output = folder / f"scene_{scene['scene_no']:03d}.wav"
            success = False

            for attempt in range(1, RETRY_LIMIT + 1):
                try:
                    logging.info(
                        "Cảnh %s | lần %s/%s",
                        scene["scene_no"],
                        attempt,
                        RETRY_LIMIT,
                    )

                    duration = generate_voice(
                        scene["narration"],
                        output,
                    )
                    mark_scene_ready(
                        scene["id"],
                        str(output),
                        duration,
                    )

                    logging.info(
                        "Đã lưu: %s | %.1f giây",
                        output,
                        duration,
                    )

                    success = True
                    remaining -= 1
                    time.sleep(2)
                    break

                except Exception as exc:
                    logging.warning(
                        "Lỗi cảnh %s: %s",
                        scene["scene_no"],
                        exc,
                    )
                    time.sleep(RETRY_DELAY_SECONDS * attempt)

            if not success:
                mark_scene_retry(
                    scene["id"],
                    "Không tạo được giọng sau nhiều lần thử",
                )
                remaining -= 1

            if remaining <= 0:
                break

        finalize_case(case["id"])

    logging.info("Agent 6 hoàn thành")

if __name__ == "__main__":
    run()
