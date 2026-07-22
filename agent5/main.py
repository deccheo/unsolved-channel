import logging
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config import (
    LOG_PATH,
    OUTPUT_DIR,
    MAX_CASES_PER_RUN,
    MAX_IMAGES_PER_RUN,
    MAX_WORKERS,
    RETRY_LIMIT,
    RETRY_DELAY_SECONDS,
)
from database import (
    migrate,
    pending_cases,
    pending_scenes,
    find_cached_image,
    mark_scene_cached,
    mark_scene_ready,
    mark_scene_retry,
    finalize_case,
)
from imagen import generate_image


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def slugify(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "case"


def is_transient_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "resource exhausted",
            "service unavailable",
            "temporarily unavailable",
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "connection error",
        )
    )


def process_scene(scene, folder: Path) -> dict:
    """Xử lý một cảnh. Mỗi worker dùng kết nối DB riêng qua các hàm database."""
    started = time.perf_counter()
    scene_no = scene["scene_no"]
    output = folder / f"scene_{scene_no:03d}.jpg"

    cached = find_cached_image(scene["visual_prompt"], scene["id"])
    if cached:
        cached_path = Path(cached["image_path"])
        if cached_path.is_file():
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached_path, output)
            mark_scene_cached(scene["id"], str(output))
            elapsed = time.perf_counter() - started
            logging.info(
                "CACHE HIT cảnh %s | dùng lại scene_id=%s | %.2f giây",
                scene_no,
                cached["id"],
                elapsed,
            )
            return {
                "success": True,
                "cache": True,
                "api_calls": 0,
                "retries": 0,
                "errors": 0,
                "elapsed": elapsed,
            }

    api_calls = 0
    retries = 0
    errors = 0
    last_error = ""

    for attempt in range(1, RETRY_LIMIT + 1):
        api_calls += 1
        if attempt > 1:
            retries += 1

        try:
            logging.info("Cảnh %s | lần %s/%s", scene_no, attempt, RETRY_LIMIT)
            api_started = time.perf_counter()
            generate_image(scene, output)
            api_elapsed = time.perf_counter() - api_started
            mark_scene_ready(scene["id"], str(output))

            elapsed = time.perf_counter() - started
            logging.info(
                "Đã lưu cảnh %s: %s | API %.2f giây | tổng %.2f giây",
                scene_no,
                output,
                api_elapsed,
                elapsed,
            )
            return {
                "success": True,
                "cache": False,
                "api_calls": api_calls,
                "retries": retries,
                "errors": errors,
                "elapsed": elapsed,
            }

        except Exception as exc:  # noqa: BLE001 - cần ghi nhận lỗi API đầy đủ
            errors += 1
            last_error = str(exc)
            transient = is_transient_error(exc)
            logging.warning(
                "Lỗi cảnh %s lần %s/%s | transient=%s | %s",
                scene_no,
                attempt,
                RETRY_LIMIT,
                transient,
                exc,
            )

            # Lỗi cố định (sai model, prompt, quyền, cấu hình...) không gọi API lặp lại.
            if not transient:
                break

            if attempt < RETRY_LIMIT:
                time.sleep(RETRY_DELAY_SECONDS * attempt)

    mark_scene_retry(scene["id"], last_error or "Không tạo được ảnh")
    elapsed = time.perf_counter() - started
    return {
        "success": False,
        "cache": False,
        "api_calls": api_calls,
        "retries": retries,
        "errors": errors,
        "elapsed": elapsed,
    }


def run() -> None:
    setup_logging()
    migrate()
    started_all = time.perf_counter()

    cases = pending_cases(MAX_CASES_PER_RUN)
    logging.info(
        "Agent 5 bắt đầu: %s hồ sơ | workers=%s | giới hạn ảnh=%s",
        len(cases),
        MAX_WORKERS,
        MAX_IMAGES_PER_RUN,
    )

    remaining = MAX_IMAGES_PER_RUN
    scene_count = 0
    api_calls = 0
    success_count = 0
    error_count = 0
    retry_count = 0
    cache_hits = 0
    scene_seconds = 0.0

    for case_index, case in enumerate(cases, 1):
        if remaining <= 0:
            break

        title = case["script_title"] or case["case_name"] or case["title"]
        folder = OUTPUT_DIR / f"{case['id']:04d}-{slugify(title)}"
        scenes = pending_scenes(case["id"], remaining)

        logging.info(
            "[%s/%s] Tạo ảnh: %s | %s cảnh trong lần chạy này",
            case_index,
            len(cases),
            title,
            len(scenes),
        )

        # MAX_WORKERS mặc định 2 để giảm nguy cơ 429/503 và khóa SQLite.
        worker_count = max(1, min(MAX_WORKERS, len(scenes))) if scenes else 1
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="agent5-image",
        ) as executor:
            future_map = {
                executor.submit(process_scene, scene, folder): scene
                for scene in scenes
            }

            for future in as_completed(future_map):
                scene = future_map[future]
                scene_count += 1
                remaining -= 1

                try:
                    result = future.result()
                except Exception as exc:  # chốt an toàn nếu worker lỗi ngoài dự kiến
                    logging.exception("Worker lỗi ở cảnh %s: %s", scene["scene_no"], exc)
                    mark_scene_retry(scene["id"], str(exc))
                    result = {
                        "success": False,
                        "cache": False,
                        "api_calls": 0,
                        "retries": 0,
                        "errors": 1,
                        "elapsed": 0.0,
                    }

                api_calls += result["api_calls"]
                retry_count += result["retries"]
                error_count += result["errors"]
                scene_seconds += result["elapsed"]

                if result["success"]:
                    success_count += 1
                if result["cache"]:
                    cache_hits += 1

        finalize_case(case["id"])

    elapsed_all = time.perf_counter() - started_all
    average_scene = scene_seconds / scene_count if scene_count else 0.0
    effective_rate = scene_count / elapsed_all if elapsed_all > 0 else 0.0

    logging.info(
        "THỐNG KÊ AGENT 5 | cảnh=%s | API calls=%s | thành công=%s | "
        "lỗi=%s | retry=%s | cache=%s | còn lại=%s | tổng=%.2fs | "
        "TB/cảnh=%.2fs | tốc độ=%.3f cảnh/s",
        scene_count,
        api_calls,
        success_count,
        error_count,
        retry_count,
        cache_hits,
        remaining,
        elapsed_all,
        average_scene,
        effective_rate,
    )
    logging.info("Agent 5 hoàn thành")


if __name__ == "__main__":
    run()
