import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from config import (
    DELETE_LOCAL_AFTER_DRIVE,
    DRIVE_FOLDER,
    DRIVE_REMOTE,
    LOW_DISK_PERCENT,
)

log = logging.getLogger("agent10")


def drive_ready() -> bool:
    result = subprocess.run(
        ["rclone", "listremotes"],
        capture_output=True, text=True, check=False
    )
    return f"{DRIVE_REMOTE}:" in result.stdout.split()


def archive_to_drive(
    video: Path,
    metadata_path: Path,
    thumbnail: Path | None,
    receipt: dict[str, Any],
) -> str:
    if not drive_ready():
        raise RuntimeError(
            f"Rclone chưa có remote {DRIVE_REMOTE}. Chạy: rclone config"
        )

    day = datetime.now().strftime("%Y-%m-%d")
    remote_dir = f"{DRIVE_REMOTE}:{DRIVE_FOLDER}/{day}/{video.stem}"

    files = [video, metadata_path]
    if thumbnail and thumbnail.exists():
        files.append(thumbnail)

    receipt_file = video.parent / f".{video.stem}.upload-receipt.json"
    receipt_file.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files.append(receipt_file)

    try:
        for path in files:
            command = [
                "rclone", "copyto", str(path),
                f"{remote_dir}/{path.name}",
                "--checksum", "--retries", "5",
                "--low-level-retries", "10",
            ]
            result = subprocess.run(
                command, capture_output=True, text=True, check=False
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "rclone thất bại")

        check = subprocess.run(
            ["rclone", "lsf", remote_dir],
            capture_output=True, text=True, check=False
        )
        if check.returncode != 0 or video.name not in check.stdout:
            raise RuntimeError("không xác minh được video trên Google Drive")

        if DELETE_LOCAL_AFTER_DRIVE:
            video.unlink(missing_ok=True)

        return remote_dir
    finally:
        receipt_file.unlink(missing_ok=True)


def free_disk_percent(path: str = "/") -> float:
    usage = shutil.disk_usage(path)
    return usage.free / usage.total * 100


def low_disk() -> bool:
    return free_disk_percent("/") < LOW_DISK_PERCENT
