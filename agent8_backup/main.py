import logging
import re
import sys
import time
from pathlib import Path

from config import (
    LOG_PATH,
    OUTPUT_DIR,
    MAX_CASES_PER_RUN,
    RETRY_LIMIT,
    RETRY_DELAY_SECONDS,
)
from database import (
    migrate,
    candidate_cases,
    best_scene_image,
    mark_ready,
    mark_retry,
)
from generator import (
    generate_background,
    fallback_background,
    compose_thumbnail,
)


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
    logging.info("Agent 8 bắt đầu: %s hồ sơ", len(cases))

    for case in cases:
        title = case_title(case)
        scene = best_scene_image(case["id"])
        output = OUTPUT_DIR / (
            f"{case['id']:04d}-{slugify(title)}-thumbnail.jpg"
        )

        logging.info("Tạo thumbnail: %s", title)

        try:
            background = None
            last_error = None

            for attempt in range(1, RETRY_LIMIT + 1):
                try:
                    logging.info(
                        "Tạo nền Gemini | lần %s/%s",
                        attempt,
                        RETRY_LIMIT,
                    )
                    background = generate_background(case, scene)
                    break

                except Exception as exc:
                    last_error = exc
                    logging.warning("Gemini lỗi: %s", exc)
                    time.sleep(RETRY_DELAY_SECONDS * attempt)

            if background is None:
                logging.warning(
                    "Dùng ảnh cảnh làm nền dự phòng: %s",
                    last_error,
                )
                background = fallback_background(scene)

            compose_thumbnail(background, case, output)
            mark_ready(case["id"], str(output))

            logging.info("Đã tạo thumbnail: %s", output)

        except Exception as exc:
            logging.exception("Lỗi thumbnail: %s", title)
            mark_retry(case["id"], str(exc))

    logging.info("Agent 8 hoàn thành")


if __name__ == "__main__":
    run()
