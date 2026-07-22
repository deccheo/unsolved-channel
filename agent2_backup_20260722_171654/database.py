import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from config import DB_PATH, BACKOFF_MINUTES, MAX_RETRIES


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA foreign_keys=ON;')
    conn.execute('PRAGMA busy_timeout=30000;')
    return conn


def migrate() -> None:
    with connect() as conn:
        columns = {r['name'] for r in conn.execute('PRAGMA table_info(cases)').fetchall()}
        additions = {
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
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f'ALTER TABLE cases ADD COLUMN {name} {definition}')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS case_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                source_name TEXT,
                published_at TEXT,
                extracted_text TEXT,
                source_type TEXT DEFAULT 'secondary',
                reliability_score INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(case_id, url),
                FOREIGN KEY(case_id) REFERENCES cases(id)
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sources_case ON case_sources(case_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_agent2_queue ON cases(verification_status, next_retry_at, overall_score, created_at)')


def pending_cases(limit: int):
    with connect() as conn:
        return conn.execute('''
            SELECT *
            FROM cases
            WHERE production_status='NEW'
              AND COALESCE(verification_status,'PENDING') IN ('PENDING','RETRY')
              AND COALESCE(retry_count,0) < ?
              AND (
                    next_retry_at IS NULL
                    OR datetime(next_retry_at) <= datetime('now')
                  )
            ORDER BY COALESCE(overall_score,0) DESC,
                     datetime(created_at) DESC,
                     id DESC
            LIMIT ?
        ''', (MAX_RETRIES, limit)).fetchall()


def add_source(case_id: int, source: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute('''
            INSERT INTO case_sources
            (case_id,url,title,source_name,published_at,extracted_text,source_type,reliability_score)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(case_id,url) DO UPDATE SET
                title=excluded.title,
                source_name=excluded.source_name,
                published_at=excluded.published_at,
                extracted_text=CASE
                    WHEN length(COALESCE(excluded.extracted_text,'')) > length(COALESCE(case_sources.extracted_text,''))
                    THEN excluded.extracted_text ELSE case_sources.extracted_text END,
                source_type=excluded.source_type,
                reliability_score=MAX(case_sources.reliability_score, excluded.reliability_score)
        ''', (
            case_id, source.get('url',''), source.get('title',''),
            source.get('source_name',''), source.get('published_at',''),
            source.get('text',''), source.get('source_type','secondary'),
            int(source.get('reliability_score',0) or 0),
        ))


def get_sources(case_id: int):
    with connect() as conn:
        return conn.execute('''
            SELECT * FROM case_sources
            WHERE case_id=?
            ORDER BY reliability_score DESC, id ASC
        ''', (case_id,)).fetchall()


def mark_verified(case_id: int, result: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute('''
            UPDATE cases SET
                verification_status='VERIFIED',
                verification_score=?,
                verified_summary=?,
                conflicts=?,
                verified_at=CURRENT_TIMESTAMP,
                production_status='VERIFIED',
                retry_count=0,
                last_retry_at=NULL,
                next_retry_at=NULL,
                verification_error=NULL
            WHERE id=?
        ''', (
            int(result.get('verification_score',0) or 0),
            result.get('verified_summary',''),
            result.get('conflicts',''),
            case_id,
        ))


def mark_review(case_id: int, result: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute('''
            UPDATE cases SET
                verification_status='NEEDS_REVIEW',
                verification_score=?,
                verified_summary=?,
                conflicts=?,
                verified_at=CURRENT_TIMESTAMP,
                production_status='REVIEW',
                next_retry_at=NULL,
                verification_error=NULL
            WHERE id=?
        ''', (
            int(result.get('verification_score',0) or 0),
            result.get('verified_summary',''),
            result.get('conflicts',''),
            case_id,
        ))


def schedule_retry(case_id: int, reason: str) -> tuple[str, int, str | None]:
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute('SELECT COALESCE(retry_count,0) AS n FROM cases WHERE id=?', (case_id,)).fetchone()
        retry_count = int(row['n'] if row else 0) + 1

        if retry_count >= MAX_RETRIES:
            conn.execute('''
                UPDATE cases SET
                    verification_status='FAILED',
                    retry_count=?,
                    last_retry_at=?,
                    next_retry_at=NULL,
                    verification_error=?,
                    production_status='FAILED'
                WHERE id=?
            ''', (retry_count, now.isoformat(), reason[:2000], case_id))
            return 'FAILED', retry_count, None

        idx = min(retry_count - 1, len(BACKOFF_MINUTES) - 1)
        minutes = BACKOFF_MINUTES[idx] if BACKOFF_MINUTES else 30
        next_retry = now + timedelta(minutes=minutes)
        conn.execute('''
            UPDATE cases SET
                verification_status='RETRY',
                retry_count=?,
                last_retry_at=?,
                next_retry_at=?,
                verification_error=?,
                production_status='NEW'
            WHERE id=?
        ''', (retry_count, now.isoformat(), next_retry.isoformat(), reason[:2000], case_id))
        return 'RETRY', retry_count, next_retry.isoformat()
