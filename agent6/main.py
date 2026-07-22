import logging
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config import (
    LOG_PATH,
    MAX_CASES_PER_RUN,
    MAX_CLIPS_PER_RUN,
    MAX_WORKERS,
    OUTPUT_DIR,
    RETRY_DELAY_SECONDS,
    RETRY_LIMIT,
)
from database import (
    finalize_case,
    find_cached_audio,
    mark_scene_cached,
    mark_scene_ready,
    mark_scene_retry,
    migrate,
    pending_cases,
    pending_scenes,
)
from tts import cache_path_for, generate_voice, normalize_narration, wave_duration


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


def is_transient_error(exc: Exception) -> bool:
    message = str(exc).lower()
    markers = (
        "429", "500", "502", "503", "504",
        "resource exhausted", "service unavailable", "timeout",
        "temporarily unavailable", "connection reset", "deadline exceeded",
    )
    return any(marker in message for marker in markers)


def generate_with_retry(scene: dict, output: Path) -> dict:
    started = time.perf_counter()
    attempts = 0
    last_error = None

    for attempt in range(1, RETRY_LIMIT + 1):
        attempts += 1
        try:
            duration = generate_voice(scene["narration"], output)
            return {
                "ok": True,
                "scene": scene,
                "output": output,
                "duration": duration,
                "attempts": attempts,
                "elapsed": time.perf_counter() - started,
            }
        except Exception as exc:
            last_error = exc
            if not is_transient_error(exc) or attempt >= RETRY_LIMIT:
                break
            time.sleep(RETRY_DELAY_SECONDS * attempt)

    return {
        "ok": False,
        "scene": scene,
        "output": output,
        "attempts": attempts,
        "error": str(last_error or "Lỗi không xác định"),
        "elapsed": time.perf_counter() - started,
    }


def try_cache(scene: dict, output: Path):
    normalized = normalize_narration(scene["narration"])

    disk_cache = cache_path_for(normalized)
    if disk_cache.is_file():
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(disk_cache, output)
        return wave_duration(output), "disk"

    cached = find_cached_audio(normalized, scene["id"])
    if cached:
        cached_path = Path(cached["audio_path"])
        if cached_path.is_file():
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached_path, output)
            return float(cached["audio_duration"] or wave_duration(output)), "database"

    return None


def run():
    setup_logging()
    migrate()
    started_all = time.perf_counter()

    cases = pending_cases(MAX_CASES_PER_RUN)
    logging.info(
        "Agent 6 TURBO bắt đầu: %s hồ sơ | workers=%s | tối đa=%s clips",
        len(cases), MAX_WORKERS, MAX_CLIPS_PER_RUN,
    )

    remaining = MAX_CLIPS_PER_RUN
    stats = {
        "scenes": 0,
        "api_calls": 0,
        "success": 0,
        "errors": 0,
        "retries": 0,
        "cache": 0,
    }

    for case_index, case in enumerate(cases, 1):
        if remaining <= 0:
            break

        title = case["script_title"] or case["case_name"] or case["title"]
        folder = OUTPUT_DIR / f"{case['id']:04d}-{slugify(title)}"
        scenes = [dict(row) for row in pending_scenes(case["id"], remaining)]

        logging.info(
            "[%s/%s] Tạo giọng: %s | %s cảnh",
            case_index, len(cases), title, len(scenes),
        )

        futures = {}
        batch_keys = {}

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for scene in scenes:
                if remaining <= 0:
                    break

                stats["scenes"] += 1
                output = folder / f"scene_{scene['scene_no']:03d}.wav"

                cached = try_cache(scene, output)
                if cached:
                    duration, source = cached
                    mark_scene_cached(scene["id"], str(output), duration)
                    stats["cache"] += 1
                    stats["success"] += 1
                    remaining -= 1
                    logging.info(
                        "CACHE HIT cảnh %s | nguồn=%s | %.1fs",
                        scene["scene_no"], source, duration,
                    )
                    continue

                key = normalize_narration(scene["narration"])
                if key in batch_keys:
                    batch_keys[key]["duplicates"].append((scene, output))
                    remaining -= 1
                    continue

                future = executor.submit(generate_with_retry, scene, output)
                futures[future] = (scene, output, key)
                batch_keys[key] = {"duplicates": []}
                remaining -= 1

            for future in as_completed(futures):
                result = future.result()
                scene = result["scene"]
                stats["api_calls"] += result["attempts"]
                stats["retries"] += max(0, result["attempts"] - 1)

                if result["ok"]:
                    mark_scene_ready(
                        scene["id"], str(result["output"]),
                        result["duration"], result["attempts"],
                    )
                    stats["success"] += 1
                    logging.info(
                        "Đã lưu cảnh %s | %.1fs audio | %.2fs xử lý | attempts=%s",
                        scene["scene_no"], result["duration"],
                        result["elapsed"], result["attempts"],
                    )

                    for duplicate, duplicate_output in batch_keys[result["scene"]["narration"] if False else normalize_narration(scene["narration"])]["duplicates"]:
                        duplicate_output.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(result["output"], duplicate_output)
                        mark_scene_cached(
                            duplicate["id"], str(duplicate_output), result["duration"]
                        )
                        stats["cache"] += 1
                        stats["success"] += 1
                        logging.info(
                            "CACHE HIT nội bộ cảnh %s từ cảnh %s",
                            duplicate["scene_no"], scene["scene_no"],
                        )
                else:
                    mark_scene_retry(scene["id"], result["error"], result["attempts"])
                    stats["errors"] += 1
                    logging.error(
                        "Lỗi cảnh %s sau %s lần: %s",
                        scene["scene_no"], result["attempts"], result["error"],
                    )

                    for duplicate, _ in batch_keys[normalize_narration(scene["narration"])]["duplicates"]:
                        mark_scene_retry(
                            duplicate["id"],
                            f"Cảnh nguồn cùng narration lỗi: {result['error']}",
                            0,
                        )
                        stats["errors"] += 1

        finalize_case(case["id"])

    elapsed = time.perf_counter() - started_all
    avg = elapsed / stats["success"] if stats["success"] else 0.0
    logging.info(
        "THỐNG KÊ AGENT 6 | cảnh=%s | API calls=%s | thành công=%s | "
        "lỗi=%s | retry=%s | cache=%s | tổng=%.2fs | TB=%.2fs/cảnh",
        stats["scenes"], stats["api_calls"], stats["success"],
        stats["errors"], stats["retries"], stats["cache"], elapsed, avg,
    )
    logging.info("Agent 6 TURBO hoàn thành")


if __name__ == "__main__":
    run()
