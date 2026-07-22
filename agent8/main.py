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
    repair_missing_ready_files,
    candidate_cases,
    best_scene_image,
    mark_running,
    mark_ready,
    mark_retry,
)
from generator import (
    generate_background,
    fallback_background,
    compose_thumbnail,
    validate_thumbnail,
)

TRANSIENT_MARKERS = (
    "429", "500", "502", "503", "504",
    "resource exhausted", "service unavailable", "timeout",
    "temporarily unavailable", "connection reset",
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


def is_transient(exc: Exception) -> bool:
    value = str(exc).lower()
    return any(marker in value for marker in TRANSIENT_MARKERS)


def run():
    setup_logging()
    migrate()
    repair_missing_ready_files()

    started = time.perf_counter()
    cases = candidate_cases(MAX_CASES_PER_RUN)
    stats = {
        "cases": len(cases), "api_calls": 0, "created": 0,
        "fallback": 0, "reused": 0, "errors": 0, "retries": 0,
    }
    logging.info("Agent 8 TURBO bắt đầu: %s hồ sơ", len(cases))

    for case in cases:
        title = case_title(case)
        scene = best_scene_image(case["id"])
        output = OUTPUT_DIR / f"{case['id']:04d}-{slugify(title)}-thumbnail.jpg"

        if output.is_file():
            try:
                validate_thumbnail(output)
                mark_ready(case["id"], str(output))
                stats["reused"] += 1
                logging.info("REUSE thumbnail: %s", output)
                continue
            except Exception:
                logging.warning("Thumbnail cũ không hợp lệ, tạo lại: %s", output)

        mark_running(case["id"])
        logging.info("Tạo thumbnail: %s", title)

        try:
            background = None
            last_error = None

            for attempt in range(1, RETRY_LIMIT + 1):
                try:
                    stats["api_calls"] += 1
                    if attempt > 1:
                        stats["retries"] += 1
                    logging.info("Tạo nền Gemini | lần %s/%s", attempt, RETRY_LIMIT)
                    background = generate_background(case, scene)
                    break
                except Exception as exc:
                    last_error = exc
                    logging.warning("Gemini lỗi: %s", exc)
                    if not is_transient(exc) or attempt >= RETRY_LIMIT:
                        break
                    time.sleep(RETRY_DELAY_SECONDS * attempt)

            if background is None:
                logging.warning("Dùng ảnh cảnh làm nền dự phòng: %s", last_error)
                background = fallback_background(scene)
                stats["fallback"] += 1

            compose_thumbnail(background, case, output)
            validate_thumbnail(output)
            mark_ready(case["id"], str(output))
            stats["created"] += 1
            logging.info("DONE thumbnail: %s", output)

        except Exception as exc:
            stats["errors"] += 1
            logging.exception("Lỗi thumbnail: %s", title)
            mark_retry(case["id"], str(exc))

    elapsed = time.perf_counter() - started
    logging.info(
        "THỐNG KÊ AGENT 8 | hồ sơ=%s | tạo mới=%s | reuse=%s | "
        "fallback=%s | API calls=%s | retry=%s | lỗi=%s | thời gian=%.2fs",
        stats["cases"], stats["created"], stats["reused"],
        stats["fallback"], stats["api_calls"], stats["retries"],
        stats["errors"], elapsed,
    )
    logging.info("Agent 8 TURBO hoàn thành")


if __name__ == "__main__":
    run()
