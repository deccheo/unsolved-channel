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
    PART_SIZE,
    ALLOW_INCOMPLETE_FINAL_PART,
    PREVIEW_MODE,
    PREVIEW_SCENE_LIMIT,
    CLEAN_TEMP_AFTER_SUCCESS,
)
from database import (
    migrate,
    all_cases,
    candidate_cases,
    ready_scenes,
    total_scene_count,
    list_parts,
    save_part,
    mark_part_retry,
    mark_partial,
    mark_pending,
    save_final_video,
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
    clip_path = work_dir / f"scene_{int(scene['scene_no']):03d}.mp4"
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


def contiguous_ready_prefix(scenes) -> list:
    """Chỉ lấy dãy READY liên tục từ cảnh 1; không bỏ qua khoảng trống."""
    prefix = []
    expected = 1
    for scene in scenes:
        scene_no = int(scene["scene_no"])
        if scene_no != expected:
            break
        prefix.append(scene)
        expected += 1
    return prefix


def eligible_parts(prefix: list, total: int) -> list[tuple[int, list]]:
    if PREVIEW_MODE:
        selected = prefix[:PREVIEW_SCENE_LIMIT]
        return [(1, selected)] if selected else []

    available = len(prefix)
    complete_story = total > 0 and available == total
    full_part_count = available // PART_SIZE
    parts = []

    for index in range(full_part_count):
        start = index * PART_SIZE
        parts.append((index + 1, prefix[start:start + PART_SIZE]))

    remainder = available % PART_SIZE
    if complete_story and remainder and ALLOW_INCOMPLETE_FINAL_PART:
        start = full_part_count * PART_SIZE
        parts.append((full_part_count + 1, prefix[start:available]))

    return parts


def render_part(case, title: str, part_no: int, scenes: list, work_dir: Path, part_dir: Path) -> dict:
    start_scene = int(scenes[0]["scene_no"])
    end_scene = int(scenes[-1]["scene_no"])
    output_path = part_dir / f"part_{part_no:03d}_s{start_scene:03d}-e{end_scene:03d}.mp4"

    # Nếu part đã tồn tại và hợp lệ, tái sử dụng ngay.
    if output_path.is_file():
        try:
            duration = validate_video(output_path)
            return {
                "path": output_path,
                "duration": duration,
                "scene_count": len(scenes),
                "start_scene": start_scene,
                "end_scene": end_scene,
                "rendered": 0,
                "reused_clips": 0,
                "reused_part": True,
                "retries": 0,
            }
        except Exception:
            output_path.unlink(missing_ok=True)

    logging.info(
        "Render part %s | %s | cảnh %s-%s (%s cảnh)",
        part_no, title, start_scene, end_scene, len(scenes),
    )

    results = []
    rendered = 0
    reused_clips = 0
    retries = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(render_one, scene, work_dir): int(scene["scene_no"])
            for scene in scenes
        }
        for completed, future in enumerate(as_completed(futures), 1):
            scene_no = futures[future]
            result = future.result()
            results.append(result)
            rendered += 0 if result["reused"] else 1
            reused_clips += 1 if result["reused"] else 0
            retries += result["retries"]
            logging.info(
                "Part %s [%s/%s] cảnh %s | %.1fs | %.1fs xử lý | %s | retry=%s",
                part_no, completed, len(scenes), scene_no, result["duration"],
                result["elapsed"], "REUSE" if result["reused"] else "RENDER",
                result["retries"],
            )

    results.sort(key=lambda item: item["scene_no"])
    clips = [item["clip_path"] for item in results]
    expected_duration = sum(item["duration"] for item in results)
    retries += concat_clips(clips, output_path, expected_duration)
    duration = validate_video(output_path, expected_duration)

    return {
        "path": output_path,
        "duration": duration,
        "scene_count": len(scenes),
        "start_scene": start_scene,
        "end_scene": end_scene,
        "rendered": rendered,
        "reused_clips": reused_clips,
        "reused_part": False,
        "retries": retries,
    }


def reconcile_database_states():
    """Sửa trạng thái cũ sai: READY chỉ hợp lệ khi đủ 100% cảnh và full.mp4 tồn tại."""
    fixed = 0
    for case in all_cases():
        case_id = int(case["id"])
        total = total_scene_count(case_id)
        prefix = contiguous_ready_prefix(list(ready_scenes(case_id)))
        done_parts = [
            row for row in list_parts(case_id)
            if row["status"] == "DONE" and row["path"] and Path(row["path"]).is_file()
        ]
        status = str(case["video_status"] or "PENDING")
        path = Path(case["video_path"]) if case["video_path"] else None
        complete = total > 0 and len(prefix) == total
        final_valid = bool(path and path.is_file() and path.name.endswith("-full.mp4"))

        if status == "READY" and not (complete and final_valid):
            if done_parts:
                mark_partial(case_id)
            else:
                mark_pending(case_id)
            fixed += 1
        elif status != "READY" and done_parts:
            # Dọn đường dẫn full cũ từng bị ghi sớm.
            mark_partial(case_id)
    if fixed:
        logging.warning("Đã sửa %s hồ sơ có trạng thái READY không hợp lệ", fixed)


def run():
    setup_logging()
    migrate()
    reconcile_database_states()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    cases = candidate_cases(MAX_CASES_PER_RUN)
    logging.info(
        "Agent 7 TURBO V3 bắt đầu: %s hồ sơ | workers=%s | part_size=%s",
        len(cases), MAX_WORKERS, PART_SIZE,
    )

    stats = {
        "parts_new": 0,
        "parts_reused": 0,
        "clips_new": 0,
        "clips_reused": 0,
        "errors": 0,
        "retries": 0,
        "finals": 0,
    }

    for case in cases:
        title = case_title(case)
        all_ready = list(ready_scenes(case["id"]))
        prefix = contiguous_ready_prefix(all_ready)
        total = total_scene_count(case["id"])
        parts = eligible_parts(prefix, total)

        target_status = "READY" if (total > 0 and len(prefix) == total) else ("PARTIAL" if parts else "PENDING")
        logging.info(
            "Hồ sơ %s | cảnh sẵn sàng liên tục=%s/%s | part đủ điều kiện=%s | trạng thái=%s",
            title, len(prefix), total, len(parts), target_status,
        )

        if not parts:
            existing_done = [r for r in list_parts(case["id"]) if r["status"] == "DONE" and r["path"] and Path(r["path"]).is_file()]
            if existing_done:
                mark_partial(case["id"])
            else:
                mark_pending(case["id"])
            needed = min(PART_SIZE, total) if total else PART_SIZE
            logging.warning(
                "Chưa đủ cảnh liên tục để tạo part: %s | hiện=%s | cần=%s | trạng thái=%s",
                title, len(prefix), needed, "PARTIAL" if existing_done else "PENDING",
            )
            continue

        case_dir = OUTPUT_DIR / f"{case['id']:04d}-{slugify(title)}"
        part_dir = case_dir / "parts"
        work_dir = TMP_DIR / f"{case['id']:04d}"
        part_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        done_from_db = {
            int(row["part_no"]): row
            for row in list_parts(case["id"])
            if row["status"] == "DONE" and row["path"]
        }

        for part_no, part_scenes in parts:
            start_scene = int(part_scenes[0]["scene_no"])
            end_scene = int(part_scenes[-1]["scene_no"])
            try:
                existing = done_from_db.get(part_no)
                if existing and Path(existing["path"]).is_file():
                    try:
                        validate_video(Path(existing["path"]))
                        logging.info("Part %s đã DONE, bỏ qua: %s", part_no, existing["path"])
                        mark_partial(case["id"])
                        stats["parts_reused"] += 1
                        continue
                    except Exception:
                        pass

                result = render_part(
                    case, title, part_no, part_scenes, work_dir, part_dir
                )
                save_part(
                    case_id=case["id"],
                    part_no=part_no,
                    start_scene=result["start_scene"],
                    end_scene=result["end_scene"],
                    scene_count=result["scene_count"],
                    path=str(result["path"]),
                    duration=result["duration"],
                )
                stats["parts_reused" if result["reused_part"] else "parts_new"] += 1
                stats["clips_new"] += result["rendered"]
                stats["clips_reused"] += result["reused_clips"]
                stats["retries"] += result["retries"]
                logging.info(
                    "Part %s DONE | %s | %.1fs | cảnh %s-%s",
                    part_no, result["path"], result["duration"],
                    result["start_scene"], result["end_scene"],
                )
            except Exception as exc:
                stats["errors"] += 1
                logging.exception("Part %s lỗi: %s", part_no, title)
                mark_part_retry(case["id"], part_no, start_scene, end_scene, str(exc))

        # Chưa đủ 100% cảnh: luôn PARTIAL và tuyệt đối không giữ video_path full.
        complete_story = total > 0 and len(prefix) == total
        if not complete_story:
            mark_partial(case["id"])
            logging.info("STATUS PARTIAL | %s/%s cảnh | chờ đủ 100%% để ghép full", len(prefix), total)

        # Chỉ khi toàn bộ cảnh liên tục đã sẵn sàng mới ghép full.
        if complete_story:
            try:
                rows = list_parts(case["id"])
                expected_parts = (total + PART_SIZE - 1) // PART_SIZE
                done_rows = [
                    row for row in rows
                    if row["status"] == "DONE" and row["path"] and Path(row["path"]).is_file()
                ]
                done_rows.sort(key=lambda row: int(row["part_no"]))
                if len(done_rows) == expected_parts and [int(r["part_no"]) for r in done_rows] == list(range(1, expected_parts + 1)):
                    final_path = OUTPUT_DIR / f"{case['id']:04d}-{slugify(title)}-full.mp4"
                    part_paths = [Path(row["path"]) for row in done_rows]
                    expected_duration = sum(float(row["duration"] or 0) for row in done_rows)
                    stats["retries"] += concat_clips(part_paths, final_path, expected_duration)
                    final_duration = validate_video(final_path, expected_duration)
                    save_final_video(case["id"], str(final_path), final_duration, total)
                    stats["finals"] += 1
                    logging.info(
                        "FINAL DONE | %s | %.1fs | %s cảnh | %s parts",
                        final_path, final_duration, total, expected_parts,
                    )
                    if CLEAN_TEMP_AFTER_SUCCESS:
                        shutil.rmtree(work_dir, ignore_errors=True)
                else:
                    logging.warning(
                        "Chưa đủ part để ghép final: %s | done=%s/%s",
                        title, len(done_rows), expected_parts,
                    )
            except Exception as exc:
                stats["errors"] += 1
                logging.exception("Lỗi ghép final: %s", title)
                mark_retry(case["id"], str(exc))

    elapsed = time.perf_counter() - started
    logging.info(
        "THỐNG KÊ AGENT 7 V3 | part mới=%s | part reuse=%s | clip mới=%s | "
        "clip reuse=%s | final=%s | lỗi=%s | retry=%s | tổng=%.1fs",
        stats["parts_new"], stats["parts_reused"], stats["clips_new"],
        stats["clips_reused"], stats["finals"], stats["errors"],
        stats["retries"], elapsed,
    )
    logging.info("Agent 7 TURBO V3 hoàn thành")


if __name__ == "__main__":
    run()
