import csv, json, logging, sys, time
from config import LOG_DIR, OUTPUT_DIR, MAX_CASES_PER_RUN, MIN_ACCEPT_SCORE
from database import init_db, insert_case, top_cases
from filtering import filter_items
from gemini_scorer import score
from rss_collector import collect

def setup_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "agent1.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

def export_csv():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "top_cases.csv"
    rows = top_cases(20)
    fields = ["id","case_name","title","country","case_type","incident_year","overall_score",
              "mystery_score","source_score","storytelling_score","audience_score","safety_score",
              "ai_summary","article_url","production_status"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k:r[k] for k in fields})
    return path

def run():
    setup_log()
    init_db()
    logging.info("Agent 1 bắt đầu")
    items = filter_items(collect())[:MAX_CASES_PER_RUN]
    logging.info("Số đề tài gửi Gemini: %s", len(items))
    added = 0
    for i, item in enumerate(items, 1):
        try:
            logging.info("[%s/%s] %s", i, len(items), item["title"])
            ai = score(item)
            suitable = (
                ai.get("is_real_case") and ai.get("is_unresolved") and ai.get("is_suitable")
                and ai.get("overall_score",0) >= MIN_ACCEPT_SCORE
                and ai.get("safety_score",0) >= 60
            )
            data = {
                "case_key": item["case_key"],
                "title": item["title"],
                "normalized_title": item["normalized_title"],
                "case_name": ai.get("case_name",""),
                "country": ai.get("country",""),
                "case_type": ai.get("case_type","other"),
                "case_status": ai.get("case_status","unknown"),
                "incident_year": ai.get("incident_year"),
                "article_url": item["url"],
                "source_name": item.get("source_name",""),
                "published_at": item.get("published_at",""),
                "article_summary": item.get("summary",""),
                "ai_summary": ai.get("short_summary",""),
                "reason": ai.get("reason",""),
                "mystery_score": ai.get("mystery_score",0),
                "source_score": ai.get("source_score",0),
                "storytelling_score": ai.get("storytelling_score",0),
                "audience_score": ai.get("audience_score",0),
                "safety_score": ai.get("safety_score",0),
                "overall_score": ai.get("overall_score",0),
                "is_suitable": int(bool(suitable)),
                "production_status": "NEW" if suitable else "REJECTED",
                "raw_json": json.dumps({"article":item,"gemini":ai}, ensure_ascii=False),
            }
            if insert_case(data):
                added += 1
            time.sleep(1.5)
        except Exception:
            logging.exception("Lỗi xử lý: %s", item.get("title"))
    path = export_csv()
    logging.info("Hoàn thành: thêm %s hồ sơ", added)
    logging.info("CSV: %s", path)

if __name__ == "__main__":
    run()
