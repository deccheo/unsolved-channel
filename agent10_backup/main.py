#!/usr/bin/env python3
import fcntl
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from config import (
    DAILY_LIMIT,
    DAILY_STATE_FILE,
    LOCK_FILE,
    LOG_FILE,
    MAX_UPLOADS_PER_RUN,
    METADATA_DIR,
    STATE_FILE,
    UPLOADED_DIR,
    VIDEOS_DIR,
)
from drive_archive import archive_to_drive, free_disk_percent, low_disk
from preflight import base_slug, validate
from uploader import upload_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("agent10")


def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data, method="POST"
            ),
            timeout=30,
        ).read()
    except Exception as exc:
        log.warning("Telegram lỗi: %s", exc)


def load_json(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def daily_count() -> int:
    today = date.today().isoformat()
    state = load_json(DAILY_STATE_FILE, {})
    if state.get("date") != today:
        state = {"date": today, "uploaded_today": 0}
        save_json(DAILY_STATE_FILE, state)
    return int(state.get("uploaded_today", 0))


def increment_daily() -> None:
    state = load_json(
        DAILY_STATE_FILE,
        {"date": date.today().isoformat(), "uploaded_today": 0},
    )
    state["date"] = date.today().isoformat()
    state["uploaded_today"] = int(state.get("uploaded_today", 0)) + 1
    save_json(DAILY_STATE_FILE, state)


def find_metadata(video: Path) -> Path | None:
    slug = base_slug(video)
    direct = METADATA_DIR / f"{slug}.json"
    if direct.exists():
        return direct
    matches = sorted(METADATA_DIR.glob(f"{slug}*.json"))
    return matches[0] if matches else None


def discover_jobs():
    if not VIDEOS_DIR.exists():
        return []
    jobs = []
    for video in sorted(VIDEOS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime):
        metadata = find_metadata(video)
        if metadata:
            jobs.append((video, metadata))
    return jobs


def youtube_verify(result: dict) -> None:
    # Uploader đã nhận phản hồi trực tiếp từ YouTube cho video, thumbnail và playlist.
    required = ("video_id", "youtube_url", "privacyStatus", "playlistId")
    missing = [x for x in required if not result.get(x)]
    if missing:
        raise RuntimeError(f"thiếu xác nhận YouTube: {', '.join(missing)}")
    if result["privacyStatus"] != "public":
        raise RuntimeError("video chưa ở trạng thái public")


def main() -> int:
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

        state = load_json(STATE_FILE, {"uploaded": {}, "partial": {}, "blocked": {}})
        uploaded = state.setdefault("uploaded", {})
        blocked = state.setdefault("blocked", {})
        partial = state.setdefault("partial", {})

        completed = 0
        for video, metadata_path in discover_jobs():
            key = str(video.resolve())
            if key in uploaded:
                continue

            metadata = load_json(metadata_path, {})
            check = validate(video, metadata)
            if not check["ok"]:
                blocked[key] = {
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "errors": check["errors"],
                }
                save_json(STATE_FILE, state)
                log.warning("Chặn %s: %s", video.name, "; ".join(check["errors"]))
                continue

            try:
                log.info("Đang upload: %s", video)
                result = upload_video(video, metadata)
                youtube_verify(result)

                receipt = {
                    **result,
                    "metadata_file": str(metadata_path),
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "preflight": check,
                }

                thumbnail = Path(check["thumbnail"]) if check["thumbnail"] else None
                remote_path = archive_to_drive(
                    video, metadata_path, thumbnail, receipt
                )
                receipt["drive_path"] = remote_path
                receipt["local_video_deleted"] = not video.exists()

                output_receipt = UPLOADED_DIR / f"{video.stem}.json"
                save_json(output_receipt, receipt)

                uploaded[key] = receipt
                partial.pop(key, None)
                blocked.pop(key, None)
                save_json(STATE_FILE, state)
                increment_daily()

                log.info("Hoàn tất: %s | Drive: %s", result["youtube_url"], remote_path)
                send_telegram(
                    "✅ Đăng YouTube thành công\n"
                    f"{result['title']}\n"
                    f"{result['youtube_url']}\n"
                    f"Public: OK\nPlaylist: OK\nThumbnail: OK\n"
                    f"Google Drive: {remote_path}"
                )
                completed += 1
            except Exception as exc:
                partial[key] = {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc),
                }
                save_json(STATE_FILE, state)
                log.exception("Xử lý thất bại: %s", video)
                send_telegram(f"❌ Agent 10 lỗi\n{video.name}\n{exc}")

            if completed >= MAX_UPLOADS_PER_RUN:
                break
            if daily_count() >= DAILY_LIMIT:
                break

        log.info(
            "Agent 10 hoàn thành: %s video; hôm nay %s/%s.",
            completed, daily_count(), DAILY_LIMIT
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
