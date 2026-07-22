import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from config import DB_PATH, BACKOFF_MINUTES, MAX_RETRIES

SCHEMA_VERSION = 11
SOURCE_COLUMNS = {
    'id','case_id','url','title','source_name','published_at','extracted_text',
    'source_type','reliability_score','relevance_score','created_at'
}
CASE_REQUIRED_COLUMNS = {'id','production_status'}
CASE_ADDITIONS = {
    'verification_status': "TEXT DEFAULT 'PENDING'",
    'verification_score': 'INTEGER DEFAULT 0',
    'verified_summary': 'TEXT',
    'conflicts': 'TEXT',
    'verified_at': 'TEXT',
    'retry_count': 'INTEGER DEFAULT 0',
    'last_retry_at': 'TEXT',
    'next_retry_at': 'TEXT',
    'verification_error': 'TEXT',
}

def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r['name']) for r in conn.execute(f'PRAGMA table_info({table})')}

def migrate() -> None:
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'cases' not in tables:
            raise RuntimeError('Không tìm thấy bảng cases; dừng migration để tránh tạo nhầm database')
        missing_required = CASE_REQUIRED_COLUMNS - _columns(conn, 'cases')
        if missing_required:
            raise RuntimeError(f'Bảng cases thiếu cột bắt buộc: {sorted(missing_required)}')
        case_columns = _columns(conn, 'cases')
        for name, definition in CASE_ADDITIONS.items():
            if name not in case_columns:
                conn.execute(f'ALTER TABLE cases ADD COLUMN {name} {definition}')
        conn.execute('''CREATE TABLE IF NOT EXISTS case_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            source_name TEXT,
            published_at TEXT,
            extracted_text TEXT,
            source_type TEXT DEFAULT 'secondary',
            reliability_score INTEGER DEFAULT 0,
            relevance_score INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(case_id,url),
            FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
        )''')
        source_columns = _columns(conn, 'case_sources')
        if 'relevance_score' not in source_columns:
            conn.execute('ALTER TABLE case_sources ADD COLUMN relevance_score INTEGER DEFAULT 0')
        conn.execute('''CREATE TABLE IF NOT EXISTS agent2_state_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            old_verification_status TEXT,
            old_production_status TEXT,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sources_case ON case_sources(case_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sources_quality ON case_sources(case_id,reliability_score DESC,relevance_score DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_agent2_queue ON cases(verification_status,next_retry_at,production_status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_agent2_audit_case ON agent2_state_audit(case_id,created_at)')
        conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

def assert_schema() -> None:
    with connect() as conn:
        case_missing = (CASE_REQUIRED_COLUMNS | set(CASE_ADDITIONS)) - _columns(conn, 'cases')
        source_missing = SOURCE_COLUMNS - _columns(conn, 'case_sources')
        audit_missing = {'id','case_id','action','old_verification_status','old_production_status','reason','created_at'} - _columns(conn, 'agent2_state_audit')
        if case_missing or source_missing or audit_missing:
            raise RuntimeError(f'Schema không hợp lệ; cases thiếu={sorted(case_missing)}, case_sources thiếu={sorted(source_missing)}, audit thiếu={sorted(audit_missing)}')
        fk = list(conn.execute('PRAGMA foreign_key_check'))
        if fk:
            raise RuntimeError(f'Foreign key lỗi: {fk[:5]}')

def pending_cases(limit: int):
    with connect() as conn:
        return conn.execute('''SELECT * FROM cases
            WHERE production_status='NEW'
              AND COALESCE(verification_status,'PENDING') IN ('PENDING','RETRY')
              AND COALESCE(retry_count,0) < ?
              AND (next_retry_at IS NULL OR datetime(next_retry_at) <= datetime('now'))
            ORDER BY COALESCE(overall_score,0) DESC,datetime(created_at) DESC,id DESC LIMIT ?''',
            (MAX_RETRIES, limit)).fetchall()

def add_source(case_id: int, source: dict[str, Any]) -> bool:
    url = str(source.get('url','')).strip()
    if not url:
        return False
    with connect() as conn:
        conn.execute('''INSERT INTO case_sources
            (case_id,url,title,source_name,published_at,extracted_text,source_type,reliability_score,relevance_score)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(case_id,url) DO UPDATE SET
              title=CASE WHEN length(COALESCE(excluded.title,''))>length(COALESCE(case_sources.title,'')) THEN excluded.title ELSE case_sources.title END,
              source_name=CASE WHEN excluded.source_name<>'' THEN excluded.source_name ELSE case_sources.source_name END,
              published_at=CASE WHEN excluded.published_at<>'' THEN excluded.published_at ELSE case_sources.published_at END,
              extracted_text=CASE WHEN length(COALESCE(excluded.extracted_text,''))>length(COALESCE(case_sources.extracted_text,'')) THEN excluded.extracted_text ELSE case_sources.extracted_text END,
              source_type=CASE WHEN excluded.reliability_score>=COALESCE(case_sources.reliability_score,0) THEN excluded.source_type ELSE case_sources.source_type END,
              reliability_score=MAX(COALESCE(case_sources.reliability_score,0),excluded.reliability_score),
              relevance_score=MAX(COALESCE(case_sources.relevance_score,0),excluded.relevance_score)''',
            (case_id,url,str(source.get('title','')),str(source.get('source_name','')),str(source.get('published_at','')),
             str(source.get('text','')),str(source.get('source_type','secondary')),
             int(source.get('reliability_score',0) or 0),int(source.get('relevance_score',0) or 0)))
    return True

def get_sources(case_id: int):
    with connect() as conn:
        return conn.execute('''SELECT id,case_id,url,title,source_name,published_at,extracted_text,
            source_type,reliability_score,relevance_score,created_at
            FROM case_sources WHERE case_id=?
            ORDER BY reliability_score DESC,relevance_score DESC,id ASC''',(case_id,)).fetchall()

def count_usable_sources(conn: sqlite3.Connection, case_id: int, min_text_length: int, min_reliability: int, min_relevance: int) -> int:
    row = conn.execute('''SELECT COUNT(*) AS n FROM case_sources
        WHERE case_id=?
          AND length(trim(COALESCE(extracted_text,''))) >= ?
          AND COALESCE(reliability_score,0) >= ?
          AND COALESCE(relevance_score,0) >= ?''',
        (case_id,int(min_text_length),int(min_reliability),int(min_relevance))).fetchone()
    return int(row['n'] if row else 0)

def _json_text(value: Any) -> str:
    import json
    return value if isinstance(value,str) else json.dumps(value or [],ensure_ascii=False)

def mark_verified_guarded(case_id: int, result: dict[str, Any], min_usable_sources: int, min_text_length: int, min_reliability: int, min_relevance: int) -> int:
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        usable_count = count_usable_sources(conn,case_id,min_text_length,min_reliability,min_relevance)
        if usable_count < int(min_usable_sources):
            raise RuntimeError(f'Không thể VERIFIED: nguồn đã lưu trong DB không đủ {usable_count}/{min_usable_sources}')
        current = conn.execute('SELECT id FROM cases WHERE id=?',(case_id,)).fetchone()
        if current is None:
            raise RuntimeError(f'Không tồn tại case id={case_id}')
        conn.execute('''UPDATE cases SET verification_status='VERIFIED',verification_score=?,verified_summary=?,conflicts=?,
            verified_at=CURRENT_TIMESTAMP,production_status='VERIFIED',retry_count=0,last_retry_at=NULL,next_retry_at=NULL,
            verification_error=NULL WHERE id=?''',
            (int(result.get('verification_score',0) or 0),str(result.get('verified_summary','')),_json_text(result.get('conflicts')),case_id))
        return usable_count

def mark_review(case_id: int, result: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute('''UPDATE cases SET verification_status='NEEDS_REVIEW',verification_score=?,verified_summary=?,conflicts=?,
            verified_at=CURRENT_TIMESTAMP,production_status='REVIEW',next_retry_at=NULL,verification_error=NULL WHERE id=?''',
            (int(result.get('verification_score',0) or 0),str(result.get('verified_summary','')),_json_text(result.get('conflicts')),case_id))

def repair_orphan_verified(min_usable_sources: int, min_text_length: int, min_reliability: int, min_relevance: int) -> list[int]:
    repaired = []
    reason = (f'Agent 2 V11 repair: VERIFIED nhưng nguồn persisted không đủ; yêu cầu nguồn={min_usable_sources}, '
              f'text>={min_text_length}, reliability>={min_reliability}, relevance>={min_relevance}')
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute('''SELECT id,verification_status,production_status FROM cases
            WHERE COALESCE(verification_status,'')='VERIFIED' OR COALESCE(production_status,'')='VERIFIED'
            ORDER BY id''').fetchall()
        for row in rows:
            count = count_usable_sources(conn,int(row['id']),min_text_length,min_reliability,min_relevance)
            if count >= int(min_usable_sources):
                continue
            conn.execute('''INSERT INTO agent2_state_audit(case_id,action,old_verification_status,old_production_status,reason)
                VALUES (?,?,?,?,?)''',(int(row['id']),'RESET_ORPHAN_VERIFIED',str(row['verification_status'] or ''),str(row['production_status'] or ''),reason))
            conn.execute('''UPDATE cases SET verification_status='PENDING',verification_score=0,verified_summary=NULL,conflicts=NULL,
                verified_at=NULL,production_status='NEW',retry_count=0,last_retry_at=NULL,next_retry_at=NULL,verification_error=?
                WHERE id=?''',(reason[:2000],int(row['id'])))
            repaired.append(int(row['id']))
    return repaired

def schedule_retry(case_id: int, reason: str) -> tuple[str,int,str|None]:
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute('SELECT COALESCE(retry_count,0) n FROM cases WHERE id=?',(case_id,)).fetchone()
        if row is None:
            raise RuntimeError(f'Không tồn tại case id={case_id}')
        retry_count = int(row['n']) + 1
        if retry_count >= MAX_RETRIES:
            conn.execute('''UPDATE cases SET verification_status='FAILED',retry_count=?,last_retry_at=?,next_retry_at=NULL,
                verification_error=?,production_status='FAILED' WHERE id=?''',(retry_count,now.isoformat(),reason[:2000],case_id))
            return 'FAILED',retry_count,None
        delay = BACKOFF_MINUTES[min(retry_count-1,len(BACKOFF_MINUTES)-1)]
        next_retry = now + timedelta(minutes=delay)
        conn.execute('''UPDATE cases SET verification_status='RETRY',retry_count=?,last_retry_at=?,next_retry_at=?,
            verification_error=?,production_status='NEW' WHERE id=?''',(retry_count,now.isoformat(),next_retry.isoformat(),reason[:2000],case_id))
        return 'RETRY',retry_count,next_retry.isoformat()
