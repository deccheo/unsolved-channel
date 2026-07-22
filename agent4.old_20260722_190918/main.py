import csv
import json
import logging
import re
import sys

from config import LOG_PATH, OUTPUT_DIR, MAX_CASES_PER_RUN, MIN_SCENES
from database import migrate, pending_cases, save_scenes, mark_retry
from planner import plan

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

def export_files(case, scenes):
    folder = OUTPUT_DIR / f"{case['id']:04d}-{slugify(case['script_title'] or case['title'])}"
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "scenes.json").write_text(
        json.dumps(scenes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fields = [
        "scene_no", "narration", "duration_seconds", "visual_type",
        "visual_prompt", "on_screen_text", "source_note", "disclaimer_label"
    ]
    with (folder / "scenes.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{k: s.get(k, "") for k in fields} for s in scenes])

    return folder

def run():
    setup_logging()
    migrate()
    cases = pending_cases(MAX_CASES_PER_RUN)
    logging.info("Agent 4 bắt đầu: %s hồ sơ", len(cases))

    for index, case in enumerate(cases, 1):
        name = case["script_title"] or case["case_name"] or case["title"]
        logging.info("[%s/%s] Chia cảnh: %s", index, len(cases), name)

        try:
            scenes = plan(case)

            if len(scenes) < MIN_SCENES:
                raise ValueError(f"Số cảnh quá ít: {len(scenes)}")

            save_scenes(case["id"], scenes)
            folder = export_files(case, scenes)
            total_seconds = sum(float(s.get("duration_seconds", 0)) for s in scenes)

            logging.info(
                "Đã tạo %s cảnh | %.1f phút | %s",
                len(scenes),
                total_seconds / 60,
                folder,
            )

        except Exception:
            logging.exception("Lỗi chia cảnh: %s", name)
            mark_retry(case["id"])

    logging.info("Agent 4 hoàn thành")

if __name__ == "__main__":
    run()
