import json
import logging
import sys
from config import (
    LOG_PATH, MAX_CASES_PER_RUN, MAX_SOURCES_PER_CASE,
    MIN_USABLE_SOURCES, MIN_VERIFIED_SCORE,
)
from database import (
    migrate, pending_cases, add_source, get_sources,
    mark_verified, mark_review, schedule_retry,
)
from research import google_news, extract_text
from verifier import verify


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[
            logging.FileHandler(LOG_PATH, encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run() -> None:
    setup_logging()
    migrate()
    cases = pending_cases(MAX_CASES_PER_RUN)
    logging.info('Agent 2 V3 bắt đầu | hàng chờ=%s', len(cases))

    stats = {'verified': 0, 'review': 0, 'retry': 0, 'failed': 0, 'error': 0}

    for index, case in enumerate(cases, 1):
        name = case['case_name'] or case['title']
        logging.info('[%s/%s] Kiểm chứng: %s | điểm=%s | retry=%s',
                     index, len(cases), name, case['overall_score'], case['retry_count'])
        try:
            found = google_news(name, case['country'] or '')
            for source in found[:MAX_SOURCES_PER_CASE]:
                extracted = extract_text(source['url'])

                fallback = ' '.join([
                    str(source.get('title', '') or ''),
                    str(source.get('summary', '') or ''),
                    str(source.get('source_name', '') or ''),
                    str(source.get('published_at', '') or ''),
                ]).strip()

                source['text'] = (
                    extracted
                    if len(extracted.strip()) >= 200
                    else fallback
                )
                add_source(case['id'], source)

            sources = get_sources(case['id'])
            usable = [s for s in sources if len((s['extracted_text'] or '').strip()) >= 200]

            if len(usable) < MIN_USABLE_SOURCES:
                status, retry_count, next_retry = schedule_retry(
                    case['id'],
                    f'Chưa đủ nguồn có nội dung: {len(usable)}/{MIN_USABLE_SOURCES}',
                )
                stats['failed' if status == 'FAILED' else 'retry'] += 1
                logging.warning('%s | nguồn=%s | retry=%s | lần kế=%s',
                                status, len(usable), retry_count, next_retry or '-')
                continue

            result = verify(case, usable)
            score = int(result.get('verification_score', 0) or 0)
            recommendation = result.get('recommendation', 'NEEDS_REVIEW')
            legal_risk = result.get('legal_risk', 'MEDIUM')
            result['conflicts'] = json.dumps(result.get('conflicts', []), ensure_ascii=False)

            verified = (
                bool(result.get('real_case'))
                and bool(result.get('unresolved'))
                and bool(result.get('enough_sources'))
                and score >= MIN_VERIFIED_SCORE
                and recommendation == 'VERIFIED'
                and legal_risk in ('LOW', 'MEDIUM')
            )

            if verified:
                mark_verified(case['id'], result)
                stats['verified'] += 1
                logging.info('VERIFIED | điểm=%s | nguồn=%s', score, len(usable))
            else:
                mark_review(case['id'], result)
                stats['review'] += 1
                logging.info('NEEDS_REVIEW | điểm=%s | khuyến nghị=%s | risk=%s',
                             score, recommendation, legal_risk)

        except Exception as exc:
            logging.exception('Lỗi kiểm chứng: %s', name)
            status, retry_count, next_retry = schedule_retry(case['id'], str(exc))
            stats['failed' if status == 'FAILED' else 'retry'] += 1
            stats['error'] += 1
            logging.warning('%s sau lỗi | retry=%s | lần kế=%s',
                            status, retry_count, next_retry or '-')

    logging.info(
        'THỐNG KÊ AGENT 2 V3 | verified=%s | review=%s | retry=%s | failed=%s | lỗi=%s',
        stats['verified'], stats['review'], stats['retry'], stats['failed'], stats['error'],
    )
    logging.info('Agent 2 V3 hoàn thành')


if __name__ == '__main__':
    run()
