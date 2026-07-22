from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

from .config import LOG_PATH, OUTPUT_DIR, MAX_CASES_PER_RUN, MIN_QA_SCORE
from .database import (
    migrate, assert_schema, pending_cases, script_claims_for,
    replace_scenes, mark_review, mark_retry
)
from .splitter import create_scene_plan

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
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "case"

def case_title(case) -> str:
    keys = set(case.keys())
    for field in ("script_title", "case_name", "title"):
        if field in keys and case[field]:
            return str(case[field])
    return f"case-{case['id']}"

def export_plan(case, scenes: list[dict], qa: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    folder = OUTPUT_DIR / f"{int(case['id']):04d}-{slugify(case_title(case))}"
    folder.mkdir(parents=True, exist_ok=True)

    payload = {
        "case_id": int(case["id"]),
        "title": case_title(case),
        "qa": qa,
        "scenes": scenes,
    }
    tmp = folder / "scenes.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(folder / "scenes.json")
    return folder

def run() -> None:
    setup_logging()
    migrate()
    assert_schema()

    cases = pending_cases(MAX_CASES_PER_RUN)
    stats = {"ready": 0, "review": 0, "retry": 0, "errors": 0, "scenes": 0}
    logging.info("Agent 4 V2.0 bắt đầu | hàng chờ=%s", len(cases))

    for index, case in enumerate(cases, 1):
        title = case_title(case)
        logging.info("[%s/%s] Chia cảnh: %s", index, len(cases), title)
        try:
            claims = script_claims_for(int(case["id"]))
            scenes, qa = create_scene_plan(case, claims)

            if not scenes:
                raise RuntimeError("Gemini không tạo được cảnh")

            if not qa.get("passed") or int(qa.get("score", 0)) < MIN_QA_SCORE:
                reason = f"QA cảnh chưa đạt: {qa.get('score',0)}/{MIN_QA_SCORE}; {qa.get('issues',[])}"
                mark_review(int(case["id"]), reason)
                stats["review"] += 1
                logging.warning("NEEDS_REVIEW | %s | %s", title, reason)
                continue

            # Commit DB atomically first. Agent 5/6 only see production_status=SCENED after success.
            replace_scenes(int(case["id"]), scenes, int(qa["score"]))
            folder = export_plan(case, scenes, qa)
            stats["ready"] += 1
            stats["scenes"] += len(scenes)
            logging.info(
                "READY | %s | cảnh=%s | QA=%s | %s",
                title, len(scenes), qa["score"], folder
            )
        except Exception as exc:
            stats["errors"] += 1
            stats["retry"] += 1
            logging.exception("Lỗi Agent 4: %s", title)
            mark_retry(int(case["id"]), str(exc))

    logging.info(
        "THỐNG KÊ AGENT 4 V2.0 | ready=%s | review=%s | retry=%s | "
        "errors=%s | scenes=%s",
        stats["ready"], stats["review"], stats["retry"],
        stats["errors"], stats["scenes"]
    )
    logging.info("Agent 4 V2.0 hoàn thành")

if __name__ == "__main__":
    run()
