#!/usr/bin/env python3
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import BASE_DIR, MAX_ITEMS_PER_RUN, METADATA_DIR, OUTPUT_DIR, STATE_FILE
from generator import generate_for_source

LOG_FILE = BASE_DIR / "agent9" / "logs" / "agent9.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("agent9")


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "story"


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"processed": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"processed": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def discover_sources() -> list[tuple[Path, str]]:
    patterns = [
        OUTPUT_DIR / "stories",
        OUTPUT_DIR / "scripts",
        BASE_DIR / "agent2" / "output",
        OUTPUT_DIR,
    ]
    candidates: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    for folder in patterns:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.json")):
            if path.parent == METADATA_DIR or path.name == "state.json":
                continue
            if path in seen:
                continue
            seen.add(path)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            marker = " ".join(data.keys()).lower()
            if not any(k in marker for k in ("title", "story", "script", "summary", "synopsis")):
                continue
            raw_id = str(
                data.get("id")
                or data.get("story_id")
                or data.get("slug")
                or (path.parent.name if path.name == "metadata.json" else path.stem)
            )
            candidates.append((path, slugify(raw_id)))
    return candidates


def main() -> int:
    log.info("Agent 9 bắt đầu")
    state = load_state()
    processed = state.setdefault("processed", {})
    count = 0

    sources = discover_sources()
    if not sources:
        log.warning("Không tìm thấy file truyện JSON để tạo metadata.")
        return 0

    for source_path, slug in sources:
        metadata_path = METADATA_DIR / f"{slug}.json"
        fingerprint = f"{source_path.stat().st_mtime_ns}:{source_path.stat().st_size}"

        if metadata_path.exists() and processed.get(str(source_path)) == fingerprint:
            continue

        try:
            log.info("Đang tạo SEO: %s", source_path)
            result = generate_for_source(source_path, slug)
            processed[str(source_path)] = fingerprint
            state["last_success"] = datetime.now(timezone.utc).isoformat()
            save_state(state)
            log.info("Đã tạo metadata: %s", result)
            count += 1
        except Exception:
            log.exception("Lỗi khi xử lý %s", source_path)

        if count >= MAX_ITEMS_PER_RUN:
            break

    log.info("Agent 9 hoàn thành, đã tạo %s bộ metadata", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
