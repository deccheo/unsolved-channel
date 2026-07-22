from __future__ import annotations

import json
import sqlite3
from typing import Any

from config import DB_PATH, MAX_SCRIPT_RETRIES

CASE_COLUMNS = {
    "script_status": "TEXT DEFAULT 'PENDING'",
    "script_title": "TEXT",
    "script_hook": "TEXT",
    "script_text": "TEXT",
    "script_disclaimer": "TEXT",
    "script_word_count": "INTEGER DEFAULT 0",
    "script_qa_score": "INTEGER DEFAULT 0",
    "script_qa_notes": "TEXT",
    "script_retry_count": "INTEGER DEFAULT 0",
    "script_last_error": "TEXT",
    "script_created_at": "TEXT",
}

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")}

def migrate() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "cases" not in tables:
            raise RuntimeError("Không tìm thấy bảng cases; không tự tạo để tránh phá pipeline")

        cols = _columns(conn, "cases")
        for name, definition in CASE_COLUMNS.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {name} {definition}")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS script_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                claim_text TEXT NOT NULL,
                source_urls TEXT NOT NULL DEFAULT '[]',
                confidence TEXT NOT NULL DEFAULT 'MEDIUM',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent3_queue
            ON cases(verification_status, script_status, script_retry_count, overall_score)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_script_claims_case
            ON script_claims(case_id)
        """)

def assert_schema() -> None:
    with connect() as conn:
        case_cols = _columns(conn, "cases")
        missing = set(CASE_COLUMNS) - case_cols
        if missing:
            raise RuntimeError(f"Schema cases thiếu cột: {sorted(missing)}")
        source_cols = _columns(conn, "case_sources")
        required = {"case_id", "url", "title", "source_name", "extracted_text", "reliability_score"}
        missing_sources = required - source_cols
        if missing_sources:
            raise RuntimeError(f"Schema case_sources thiếu cột: {sorted(missing_sources)}")

def pending_cases(limit: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("""
            SELECT *
            FROM cases
            WHERE COALESCE(verification_status, '') = 'VERIFIED'
              AND COALESCE(script_status, 'PENDING') IN ('PENDING', 'RETRY')
              AND COALESCE(script_retry_count, 0) < ?
              AND COALESCE(production_status, 'NEW') NOT IN ('SCRIPTED','SCENED','RENDERED','PUBLISHED')
            ORDER BY COALESCE(verification_score, 0) DESC,
                     COALESCE(overall_score, 0) DESC,
                     id ASC
            LIMIT ?
        """, (MAX_SCRIPT_RETRIES, limit)).fetchall()

def sources_for(case_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        cols = _columns(conn, "case_sources")
        relevance_expr = "COALESCE(relevance_score,0)" if "relevance_score" in cols else "0"
        return conn.execute(f"""
            SELECT id, case_id, url, title, source_name, published_at,
                   extracted_text, source_type,
                   COALESCE(reliability_score,0) AS reliability_score,
                   {relevance_expr} AS relevance_score
            FROM case_sources
            WHERE case_id=?
              AND length(trim(COALESCE(extracted_text,''))) > 0
            ORDER BY COALESCE(reliability_score,0) DESC,
                     {relevance_expr} DESC,
                     id ASC
        """, (case_id,)).fetchall()

def save_script(case_id: int, result: dict[str, Any], qa: dict[str, Any]) -> None:
    claims = result.get("claims") or []
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM script_claims WHERE case_id=?", (case_id,))
        for claim in claims:
            conn.execute("""
                INSERT INTO script_claims(case_id, claim_text, source_urls, confidence)
                VALUES (?,?,?,?)
            """, (
                case_id,
                str(claim.get("claim", "")).strip(),
                json.dumps(claim.get("source_urls", []), ensure_ascii=False),
                str(claim.get("confidence", "MEDIUM")).upper(),
            ))
        conn.execute("""
            UPDATE cases SET
                script_status='APPROVED',
                script_title=?,
                script_hook=?,
                script_text=?,
                script_disclaimer=?,
                script_word_count=?,
                script_qa_score=?,
                script_qa_notes=?,
                script_retry_count=0,
                script_last_error=NULL,
                script_created_at=CURRENT_TIMESTAMP,
                production_status='SCRIPTED'
            WHERE id=?
        """, (
            result.get("title", ""),
            result.get("hook", ""),
            result.get("script", ""),
            result.get("disclaimer", ""),
            int(result.get("word_count", 0)),
            int(qa.get("score", 0)),
            json.dumps(qa, ensure_ascii=False),
            case_id,
        ))

def mark_retry(case_id: int, error: str) -> None:
    with connect() as conn:
        conn.execute("""
            UPDATE cases SET
                script_status=CASE
                    WHEN COALESCE(script_retry_count,0)+1 >= ? THEN 'FAILED'
                    ELSE 'RETRY'
                END,
                script_retry_count=COALESCE(script_retry_count,0)+1,
                script_last_error=?
            WHERE id=?
        """, (MAX_SCRIPT_RETRIES, error[:2000], case_id))

def mark_needs_review(case_id: int, error: str, result: dict[str, Any] | None = None) -> None:
    result = result or {}
    with connect() as conn:
        conn.execute("""
            UPDATE cases SET
                script_status='NEEDS_REVIEW',
                script_title=?,
                script_hook=?,
                script_text=?,
                script_disclaimer=?,
                script_word_count=?,
                script_last_error=?,
                script_created_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (
            result.get("title", ""),
            result.get("hook", ""),
            result.get("script", ""),
            result.get("disclaimer", ""),
            int(result.get("word_count", 0)),
            error[:2000],
            case_id,
        ))
