import logging, sys
from config import (LOG_PATH,MAX_CASES_PER_RUN,MAX_SOURCES_PER_CASE,MIN_USABLE_SOURCES,MIN_VERIFIED_SCORE,
                    MIN_TEXT_LENGTH,MIN_RELIABILITY,MIN_RELEVANCE)
from database import migrate,assert_schema,pending_cases,add_source,get_sources,mark_verified,mark_review,schedule_retry
from research import extract_text,search_sources
from verifier import verify
VERSION='10.0'

def setup_logging():
    LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
    root=logging.getLogger(); root.setLevel(logging.INFO)
    if not root.handlers:
        fmt=logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
        for h in (logging.FileHandler(LOG_PATH,encoding='utf-8'),logging.StreamHandler(sys.stdout)):
            h.setFormatter(fmt); root.addHandler(h)

def _case_name(case): return str(case['case_name'] or case['title'] or '').strip()
def _usable_sources(sources):
    return [s for s in sources if len(str(s['extracted_text'] or '').strip())>=MIN_TEXT_LENGTH
            and int(s['reliability_score'] or 0)>=MIN_RELIABILITY and int(s['relevance_score'] or 0)>=MIN_RELEVANCE]

def process_case(case,search_fn=search_sources,extract_fn=extract_text,verify_fn=verify):
    name=_case_name(case)
    if not name:
        status,*rest=schedule_retry(case['id'],'Case thiếu tên'); return status
    found=search_fn(name,case['country'] or '')
    logging.info('Tìm thấy %s URL nguồn',len(found))
    for source in found[:MAX_SOURCES_PER_CASE]:
        try:
            extracted=extract_fn(source['url'])
            fallback=' '.join([str(source.get('title','')),str(source.get('summary','')),str(source.get('source_name',''))]).strip()
            source['text']=extracted if len(extracted.strip())>=MIN_TEXT_LENGTH else fallback
            add_source(case['id'],source)
            logging.info('Nguồn: %s | tin cậy=%s | liên quan=%s | nội dung=%s',source.get('source_name') or source.get('url'),source.get('reliability_score',0),source.get('relevance_score',0),len(source['text']))
        except Exception as exc:
            logging.warning('Bỏ qua nguồn lỗi %s: %s',source.get('url',''),exc)
    usable=_usable_sources(get_sources(case['id']))
    if len(usable)<MIN_USABLE_SOURCES:
        status,retry_count,next_retry=schedule_retry(case['id'],f'Chưa đủ nguồn phù hợp: {len(usable)}/{MIN_USABLE_SOURCES}')
        logging.warning('%s | nguồn=%s | retry=%s | lần kế=%s',status,len(usable),retry_count,next_retry or '-')
        return status
    result=verify_fn(case,usable)
    score=int(result.get('verification_score',0) or 0); recommendation=str(result.get('recommendation','NEEDS_REVIEW')).upper(); risk=str(result.get('legal_risk','MEDIUM')).upper()
    verified=(bool(result.get('real_case')) and bool(result.get('unresolved')) and bool(result.get('enough_sources')) and score>=MIN_VERIFIED_SCORE and recommendation=='VERIFIED' and risk in ('LOW','MEDIUM'))
    if verified: mark_verified(case['id'],result); logging.info('VERIFIED | điểm=%s | nguồn=%s',score,len(usable)); return 'VERIFIED'
    mark_review(case['id'],result); logging.info('NEEDS_REVIEW | điểm=%s | khuyến nghị=%s | risk=%s',score,recommendation,risk); return 'NEEDS_REVIEW'

def run():
    setup_logging(); migrate(); assert_schema(); cases=pending_cases(MAX_CASES_PER_RUN)
    logging.info('Agent 2 V%s bắt đầu | hàng chờ=%s',VERSION,len(cases)); stats={'VERIFIED':0,'NEEDS_REVIEW':0,'RETRY':0,'FAILED':0,'ERROR':0}
    for i,case in enumerate(cases,1):
        logging.info('[%s/%s] Kiểm chứng: %s | điểm=%s | retry=%s',i,len(cases),_case_name(case),case['overall_score'],case['retry_count'])
        try: status=process_case(case); stats[status]=stats.get(status,0)+1
        except Exception as exc:
            logging.exception('Lỗi kiểm chứng: %s',_case_name(case)); status,_,_=schedule_retry(case['id'],str(exc)); stats[status]=stats.get(status,0)+1; stats['ERROR']+=1
    logging.info('THỐNG KÊ AGENT 2 V%s | %s',VERSION,' | '.join(f'{k.lower()}={v}' for k,v in stats.items())); logging.info('Agent 2 V%s hoàn thành',VERSION)
if __name__=='__main__': run()
