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
    TMP_DIR,
    MAX_CASES_PER_RUN,
    MAX_WORKERS,
    PREVIEW_MODE,
    PREVIEW_SCENE_LIMIT,
    CLEAN_TEMP_AFTER_SUCCESS,
)
from database import (
    migrate,
    candidate_cases,
    ready_scenes,
    total_scene_count,
    save_video,
    mark_retry,
)
from renderer import make_scene_clip, concat_clips, validate_video


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


def render_one(scene, work_dir: Path) -> dict:
    started = time.perf_counter()
    clip_path = work_dir / f"scene_{scene['scene_no']:03d}.mp4"
    result = make_scene_clip(
        Path(scene["image_path"]),
        Path(scene["audio_path"]),
        clip_path,
        int(scene["scene_no"]),
    )
    return {
        "scene_no": int(scene["scene_no"]),
        "clip_path": clip_path,
        "duration": float(result["duration"]),
        "reused": bool(result["reused"]),
        "retries": int(result["retries"]),
        "elapsed": time.perf_counter() - started,
    }


def run():
    setup_logging()
    migrate()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    run_started = time.perf_counter()
    cases = candidate_cases(MAX_CASES_PER_RUN)
    logging.info("Agent 7 TURBO bắt đầu: %s hồ sơ | workers=%s", len(cases), MAX_WORKERS)

    total_rendered = 0
    total_reused = 0
    total_retries = 0
    total_failed = 0

    for case in cases:
        title = case_title(case)
        ready = list(ready_scenes(case["id"]))
        total = total_scene_count(case["id"])

        if not ready:
            logging.warning("Không có cảnh đủ ảnh và giọng: %s", title)
            continue

        selected = ready[:PREVIEW_SCENE_LIMIT] if PREVIEW_MODE else ready
        if not PREVIEW_MODE and len(selected) != total:
            logging.warning(
                "Chưa đủ cảnh để render final: %s | đủ=%s/%s. Giữ PENDING.",
                title, len(selected), total,
            )
            continue

        work_dir = TMP_DIR / f"{case['id']:04d}"
        work_dir.mkdir(parents=True, exist_ok=True)

        mode = "preview" if PREVIEW_MODE else "final"
        output_path = OUTPUT_DIR / f"{case['id']:04d}-{slugify(title)}-{mode}.mp4"
        logging.info("Render: %s | %s/%s cảnh", title, len(selected), total)

        try:
            results = []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(render_one, scene, work_dir): int(scene["scene_no"])
                    for scene in selected
                }
                for completed, future in enumerate(as_completed(futures), 1):
                    scene_no = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        total_failed += 1
                        raise RuntimeError(f"Cảnh {scene_no} lỗi: {exc}") from exc
                    results.append(result)
                    total_rendered += 0 if result["reused"] else 1
                    total_reused += 1 if result["reused"] else 0
                    total_retries += result["retries"]
                    logging.info(
                        "[%s/%s] Cảnh %s | %.1fs | xử lý %.1fs | %s | retry=%s",
                        completed, len(selected), result["scene_no"], result["duration"],
                        result["elapsed"], "REUSE" if result["reused"] else "RENDER",
                        result["retries"],
                    )

            results.sort(key=lambda x: x["scene_no"])
            clips = [r["clip_path"] for r in results]
            expected_duration = sum(r["duration"] for r in results)
            concat_retries = concat_clips(clips, output_path, expected_duration)
            total_retries += concat_retries
            final_duration = validate_video(output_path, expected_duration)

            complete = not PREVIEW_MODE and len(selected) == total
            save_video(
                case_id=case["id"],
                path=str(output_path),
                duration=final_duration,
                scene_count=len(selected),
                complete=complete,
            )
            logging.info(
                "Đã tạo video: %s | %.1fs | %s cảnh | complete=%s",
                output_path, final_duration, len(selected), complete,
            )

            if CLEAN_TEMP_AFTER_SUCCESS:
                shutil.rmtree(work_dir, ignore_errors=True)

        except Exception as exc:
            logging.exception("Lỗi render: %s", title)
            mark_retry(case["id"], str(exc))

    elapsed = time.perf_counter() - run_started
    logging.info(
        "THỐNG KÊ AGENT 7 | render mới=%s | reuse=%s | lỗi=%s | retry=%s | "
        "tổng thời gian=%.1fs",
        total_rendered, total_reused, total_failed, total_retries, elapsed,
    )
    logging.info("Agent 7 TURBO hoàn thành")


if __name__ == "__main__":
    run()
