#!/usr/bin/env python3
import fcntl
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    DAILY_LIMIT, DAILY_STATE_FILE, DRIVE_ENABLED, LOCK_FILE, LOG_FILE,
    MAX_UPLOADS_PER_RUN, METADATA_DIR, REQUIRE_PUBLIC, STATE_FILE,
    UPLOADED_DIR, VIDEOS_DIR,
)
from drive_archive import archive_to_drive, free_disk_percent, low_disk
from preflight import base_slug, validate
from state_store import load_json, save_json_atomic
from uploader import upload_video

for directory in (LOG_FILE.parent, UPLOADED_DIR, VIDEOS_DIR, METADATA_DIR):
    directory.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("agent10")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST"),
            timeout=30,
        ).read()
    except Exception as exc:
        log.warning("Telegram lỗi: %s", exc)


def daily_count() -> int:
    today = date.today().isoformat()
    state = load_json(DAILY_STATE_FILE, {})
    if state.get("date") != today:
        state = {"date": today, "uploaded_today": 0}
        save_json_atomic(DAILY_STATE_FILE, state)
    return int(state.get("uploaded_today", 0))


def increment_daily() -> None:
    state = load_json(DAILY_STATE_FILE, {"date": date.today().isoformat(), "uploaded_today": 0})
    if state.get("date") != date.today().isoformat():
        state = {"date": date.today().isoformat(), "uploaded_today": 0}
    state["uploaded_today"] = int(state.get("uploaded_today", 0)) + 1
    save_json_atomic(DAILY_STATE_FILE, state)


def find_metadata(video: Path) -> Path | None:
    slug = base_slug(video)
    story_prefix = video.stem.split("-", 1)[0]
    candidates = [METADATA_DIR / f"{slug}.json"]
    candidates.extend(sorted(METADATA_DIR.glob(f"{story_prefix}-*.json")))
    candidates.extend(sorted(METADATA_DIR.glob(f"{slug}*.json")))
    return next((p for p in candidates if p.is_file()), None)


def video_rank(path: Path) -> tuple[int, float]:
    name = path.stem.lower()
    score = 0
    if "full" in name or "final" in name:
        score += 100
    if "preview" in name:
        score -= 100
    if "parts" in path.parts or name.startswith("part_"):
        score -= 200
    return score, path.stat().st_mtime


def discover_jobs() -> list[tuple[Path, Path]]:
    if not VIDEOS_DIR.exists():
        return []
    grouped: dict[str, tuple[Path, Path]] = {}
    for video in VIDEOS_DIR.rglob("*.mp4"):
        metadata = find_metadata(video)
        if metadata is None:
            continue
        key = video.stem.split("-", 1)[0]
        current = grouped.get(key)
        if current is None or video_rank(video) > video_rank(current[0]):
            grouped[key] = (video, metadata)
    return sorted(grouped.values(), key=lambda item: item[0].stat().st_mtime)


def verify_youtube(result: dict[str, Any]) -> None:
    required = ("video_id", "youtube_url", "playlistId")
    missing = [name for name in required if not result.get(name)]
    if missing:
        raise RuntimeError(f"thiếu xác nhận YouTube: {', '.join(missing)}")
    if REQUIRE_PUBLIC and result.get("privacyStatus") != "public":
        raise RuntimeError("video chưa ở trạng thái public")


def write_receipt(video: Path, receipt: dict[str, Any]) -> Path:
    path = UPLOADED_DIR / f"{video.stem}.json"
    save_json_atomic(path, receipt)
    return path


def main() -> int:
    started = time.monotonic()
    stats = {"jobs": 0, "uploaded": 0, "archived": 0, "resume": 0, "blocked": 0, "errors": 0}
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.touch(exist_ok=True)
    with LOCK_FILE.open("r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.warning("Agent 10 đang chạy ở tiến trình khác, bỏ qua.")
            return 0

        count_today = daily_count()
        if count_today >= DAILY_LIMIT:
            log.info("Đã đạt giới hạn %s video trong ngày.", DAILY_LIMIT)
            return 0
        if low_disk():
            free = free_disk_percent("/")
            send_telegram(f"⚠️ VPS chỉ còn {free:.1f}% dung lượng trống.")
            log.warning("Dung lượng VPS thấp: %.1f%%", free)

        state = load_json(STATE_FILE, {"uploaded": {}, "youtube_done": {}, "blocked": {}, "errors": {}})
        uploaded = state.setdefault("uploaded", {})
        youtube_done = state.setdefault("youtube_done", {})
        blocked = state.setdefault("blocked", {})
        errors = state.setdefault("errors", {})

        jobs = discover_jobs()
        stats["jobs"] = len(jobs)
        log.info("Agent 10 TURBO bắt đầu | jobs=%s | hôm nay=%s/%s", len(jobs), count_today, DAILY_LIMIT)

        completed_this_run = 0
        for video, metadata_path in jobs:
            key = str(video.resolve())
            if key in uploaded:
                continue
            metadata = load_json(metadata_path, {})
            check = validate(video, metadata)
            if not check["ok"]:
                blocked[key] = {"checked_at": now_iso(), "errors": check["errors"]}
                save_json_atomic(STATE_FILE, state)
                stats["blocked"] += 1
                log.warning("Chặn %s: %s", video.name, "; ".join(check["errors"]))
                continue

            try:
                receipt = youtube_done.get(key)
                if receipt:
                    stats["resume"] += 1
                    log.info("RESUME sau YouTube: %s | video_id=%s", video.name, receipt.get("video_id"))
                else:
                    log.info("UPLOAD: %s", video)
                    receipt = upload_video(video, metadata)
                    verify_youtube(receipt)
                    receipt.update({"metadata_file": str(metadata_path), "uploaded_at": now_iso(), "preflight": check})
                    youtube_done[key] = receipt
                    blocked.pop(key, None)
                    errors.pop(key, None)
                    save_json_atomic(STATE_FILE, state)
                    write_receipt(video, receipt)
                    increment_daily()
                    stats["uploaded"] += 1

                if DRIVE_ENABLED:
                    thumbnail = Path(check["thumbnail"]) if check["thumbnail"] else None
                    remote_path = archive_to_drive(video, metadata_path, thumbnail, receipt)
                    receipt["drive_path"] = remote_path
                    receipt["local_video_deleted"] = not video.exists()
                    stats["archived"] += 1
                else:
                    receipt["drive_path"] = None
                    receipt["local_video_deleted"] = False
                    log.info("Bỏ qua Drive vì AGENT10_DRIVE_ENABLED=0")

                receipt["completed_at"] = now_iso()
                write_receipt(video, receipt)
                uploaded[key] = receipt
                youtube_done.pop(key, None)
                errors.pop(key, None)
                save_json_atomic(STATE_FILE, state)
                completed_this_run += 1
                log.info("DONE: %s", receipt["youtube_url"])
                send_telegram(
                    "✅ Đăng YouTube thành công\n"
                    f"{receipt.get('title', video.stem)}\n{receipt['youtube_url']}\n"
                    f"Drive: {receipt.get('drive_path') or 'đã tắt'}"
                )
            except Exception as exc:
                errors[key] = {"updated_at": now_iso(), "error": str(exc)}
                save_json_atomic(STATE_FILE, state)
                stats["errors"] += 1
                log.exception("Xử lý thất bại: %s", video)
                send_telegram(f"❌ Agent 10 lỗi\n{video.name}\n{exc}")

            if completed_this_run >= MAX_UPLOADS_PER_RUN or daily_count() >= DAILY_LIMIT:
                break

        elapsed = time.monotonic() - started
        log.info(
            "THỐNG KÊ AGENT 10 | jobs=%s | upload mới=%s | archive=%s | resume=%s | blocked=%s | lỗi=%s | hôm nay=%s/%s | tổng=%.2fs",
            stats["jobs"], stats["uploaded"], stats["archived"], stats["resume"], stats["blocked"], stats["errors"], daily_count(), DAILY_LIMIT, elapsed,
        )
        log.info("Agent 10 TURBO hoàn thành")
        return 0


if __name__ == "__main__":
    sys.exit(main())
