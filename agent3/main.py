from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

from .config import (
    LOG_PATH, OUTPUT_DIR, MAX_CASES_PER_RUN, MIN_SOURCE_COUNT,
    MIN_SOURCE_TEXT_CHARS, MIN_QA_SCORE
)
from .database import (
    migrate, assert_schema, pending_cases, sources_for,
    save_script, mark_retry, mark_needs_review
)
from .writer import write_and_validate

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
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "case"

def export_files(case, result: dict, qa: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    folder = OUTPUT_DIR / f"{int(case['id']):04d}-{slugify(result.get('title',''))}"
    folder.mkdir(parents=True, exist_ok=True)
    tmp_script = folder / "script.txt.tmp"
    tmp_meta = folder / "metadata.json.tmp"
    tmp_script.write_text(result.get("script", ""), encoding="utf-8")
    tmp_meta.write_text(
        json.dumps({"script": result, "qa": qa}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_script.replace(folder / "script.txt")
    tmp_meta.replace(folder / "metadata.json")
    return folder

def run() -> None:
    setup_logging()
    migrate()
    assert_schema()
    cases = pending_cases(MAX_CASES_PER_RUN)
    stats = {"approved": 0, "review": 0, "retry": 0, "errors": 0}
    logging.info("Agent 3 V2.0 bắt đầu | hàng chờ=%s", len(cases))

    for index, case in enumerate(cases, 1):
        name = (case["case_name"] if "case_name" in case.keys() else "") or case["title"]
        logging.info("[%s/%s] Viết kịch bản: %s", index, len(cases), name)
        try:
            all_sources = sources_for(int(case["id"]))
            sources = [
                s for s in all_sources
                if len(str(s["extracted_text"] or "").strip()) >= MIN_SOURCE_TEXT_CHARS
            ]
            if len(sources) < MIN_SOURCE_COUNT:
                reason = f"Không đủ nguồn nội dung: {len(sources)}/{MIN_SOURCE_COUNT}"
                logging.warning("RETRY | %s | %s", name, reason)
                mark_retry(int(case["id"]), reason)
                stats["retry"] += 1
                continue

            result, qa = write_and_validate(case, sources)

            if not result.get("script"):
                raise RuntimeError("Kịch bản trống sau khi tạo")

            if not qa.get("passed") or int(qa.get("score", 0)) < MIN_QA_SCORE:
                reason = f"QA chưa đạt: {qa.get('score',0)}/{MIN_QA_SCORE}; {qa.get('issues',[])}"
                mark_needs_review(int(case["id"]), reason, result)
                stats["review"] += 1
                logging.warning("NEEDS_REVIEW | %s | QA=%s", name, qa.get("score"))
                continue

            # Lưu DB trước; chỉ export sau khi giao dịch DB thành công.
            save_script(int(case["id"]), result, qa)
            folder = export_files(case, result, qa)
            stats["approved"] += 1
            logging.info(
                "APPROVED | %s | từ=%s | QA=%s | %s",
                name, result.get("word_count", 0), qa.get("score", 0), folder
            )
        except Exception as exc:
            stats["errors"] += 1
            stats["retry"] += 1
            logging.exception("Lỗi Agent 3: %s", name)
            mark_retry(int(case["id"]), str(exc))

    logging.info(
        "THỐNG KÊ AGENT 3 V2.0 | approved=%s | review=%s | retry=%s | errors=%s",
        stats["approved"], stats["review"], stats["retry"], stats["errors"]
    )
    logging.info("Agent 3 V2.0 hoàn thành")

if __name__ == "__main__":
    run()
