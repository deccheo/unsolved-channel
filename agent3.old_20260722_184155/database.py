import sqlite3
from config import DB_PATH

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def migrate():
    with connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cases)").fetchall()}
        additions = {
            "script_status": "TEXT DEFAULT 'PENDING'",
            "script_title": "TEXT",
            "script_hook": "TEXT",
            "script_text": "TEXT",
            "script_disclaimer": "TEXT",
            "script_word_count": "INTEGER DEFAULT 0",
            "script_created_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {name} {definition}")

def pending_cases(limit: int):
    with connect() as conn:
        return conn.execute("""
            SELECT * FROM cases
            WHERE production_status='VERIFIED'
              AND COALESCE(script_status,'PENDING') IN ('PENDING','RETRY')
            ORDER BY verification_score DESC, overall_score DESC
            LIMIT ?
        """, (limit,)).fetchall()

def sources_for(case_id: int):
    with connect() as conn:
        return conn.execute("""
            SELECT title, source_name, url, extracted_text, reliability_score
            FROM case_sources
            WHERE case_id=?
            ORDER BY reliability_score DESC, id ASC
        """, (case_id,)).fetchall()

def save_script(case_id: int, result: dict):
    with connect() as conn:
        conn.execute("""
            UPDATE cases SET
                script_status='DRAFT',
                script_title=?,
                script_hook=?,
                script_text=?,
                script_disclaimer=?,
                script_word_count=?,
                script_created_at=CURRENT_TIMESTAMP,
                production_status='SCRIPTED'
            WHERE id=?
        """, (
            result.get("title",""),
            result.get("hook",""),
            result.get("script",""),
            result.get("disclaimer",""),
            result.get("word_count",0),
            case_id,
        ))

def mark_retry(case_id: int):
    with connect() as conn:
        conn.execute("""
            UPDATE cases
            SET script_status='RETRY'
            WHERE id=?
        """, (case_id,))
