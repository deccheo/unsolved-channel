import json
import logging
import re
import sys

from config import LOG_PATH, OUTPUT_DIR, MAX_CASES_PER_RUN
from database import migrate, pending_cases, sources_for, save_script, mark_retry
from writer import write_script

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

def export_files(case, result):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    folder = OUTPUT_DIR / f"{case['id']:04d}-{slugify(result.get('title',''))}"
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "script.txt").write_text(
        result.get("script",""),
        encoding="utf-8",
    )
    (folder / "metadata.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return folder

def run():
    setup_logging()
    migrate()

    cases = pending_cases(MAX_CASES_PER_RUN)
    logging.info("Agent 3 bắt đầu: %s hồ sơ", len(cases))

    for index, case in enumerate(cases, 1):
        name = case["case_name"] or case["title"]
        logging.info("[%s/%s] Viết kịch bản: %s", index, len(cases), name)

        try:
            sources = sources_for(case["id"])
            if len(sources) < 2:
                logging.warning("Không đủ nguồn cho: %s", name)
                mark_retry(case["id"])
                continue

            result = write_script(case, sources)
            if result.get("word_count", 0) < 1000:
                raise ValueError("Kịch bản quá ngắn")

            save_script(case["id"], result)
            folder = export_files(case, result)

            logging.info(
                "Đã tạo %s từ | %s",
                result.get("word_count", 0),
                folder,
            )

        except Exception:
            logging.exception("Lỗi viết kịch bản: %s", name)
            mark_retry(case["id"])

    logging.info("Agent 3 hoàn thành")

if __name__ == "__main__":
    run()
