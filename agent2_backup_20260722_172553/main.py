import json
import logging
import sys

from config import LOG_PATH, MAX_CASES_PER_RUN, MAX_SOURCES_PER_CASE, MIN_USABLE_SOURCES, MIN_VERIFIED_SCORE
from database import migrate, pending_cases, add_source, get_sources, mark_verified, mark_review, schedule_retry
from research import extract_text, search_sources
from verifier import verify

MIN_TEXT_LENGTH = 300


def setup_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH, encoding='utf-8'), logging.StreamHandler(sys.stdout)])


def run():
    setup_logging(); migrate()
    cases = pending_cases(MAX_CASES_PER_RUN)
    logging.info('Agent 2 V6 bắt đầu | hàng chờ=%s', len(cases))
    stats = {'verified':0,'review':0,'retry':0,'failed':0,'error':0}
    for index, case in enumerate(cases, 1):
        name = case['case_name'] or case['title']
        logging.info('[%s/%s] Kiểm chứng: %s | điểm=%s | retry=%s', index, len(cases), name, case['overall_score'], case['retry_count'])
        try:
            found = search_sources(name, case['country'] or '')
            logging.info('Tìm thấy %s URL nguồn từ RSS/GDELT', len(found))
            for source in found[:MAX_SOURCES_PER_CASE]:
                source['text'] = extract_text(source['url'])
                if len(source['text']) < MIN_TEXT_LENGTH:
                    fallback = ' '.join([source.get('title',''), source.get('summary',''), source.get('source_name','')]).strip()
                    source['text'] = fallback if len(fallback) > len(source['text']) else source['text']
                add_source(case['id'], source)
                logging.info('Nguồn: %s | tin cậy=%s | liên quan=%s | nội dung=%s ký tự', source.get('source_name') or source.get('url'), source.get('reliability_score',0), source.get('relevance_score',0), len(source['text']))
            sources = get_sources(case['id'])
            usable = [s for s in sources if len((s['extracted_text'] or '').strip()) >= MIN_TEXT_LENGTH]
            if len(usable) < MIN_USABLE_SOURCES:
                status, retry_count, next_retry = schedule_retry(case['id'], f'Chưa đủ nguồn có nội dung: {len(usable)}/{MIN_USABLE_SOURCES}')
                stats['failed' if status == 'FAILED' else 'retry'] += 1
                logging.warning('%s | nguồn=%s | retry=%s | lần kế=%s', status, len(usable), retry_count, next_retry or '-')
                continue
            result = verify(case, usable)
            score = int(result.get('verification_score',0) or 0)
            recommendation = result.get('recommendation','NEEDS_REVIEW'); legal_risk = result.get('legal_risk','MEDIUM')
            result['conflicts'] = json.dumps(result.get('conflicts',[]), ensure_ascii=False)
            verified = bool(result.get('real_case')) and bool(result.get('unresolved')) and bool(result.get('enough_sources')) and score >= MIN_VERIFIED_SCORE and recommendation == 'VERIFIED' and legal_risk in ('LOW','MEDIUM')
            if verified:
                mark_verified(case['id'], result); stats['verified'] += 1; logging.info('VERIFIED | điểm=%s | nguồn=%s', score, len(usable))
            else:
                mark_review(case['id'], result); stats['review'] += 1; logging.info('NEEDS_REVIEW | điểm=%s | khuyến nghị=%s | risk=%s', score, recommendation, legal_risk)
        except Exception as exc:
            logging.exception('Lỗi kiểm chứng: %s', name)
            status, retry_count, next_retry = schedule_retry(case['id'], str(exc)); stats['failed' if status == 'FAILED' else 'retry'] += 1; stats['error'] += 1
            logging.warning('%s sau lỗi | retry=%s | lần kế=%s', status, retry_count, next_retry or '-')
    logging.info('THỐNG KÊ AGENT 2 V6 | verified=%s | review=%s | retry=%s | failed=%s | lỗi=%s', stats['verified'], stats['review'], stats['retry'], stats['failed'], stats['error'])
    logging.info('Agent 2 V6 hoàn thành')

if __name__ == '__main__': run()
