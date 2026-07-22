import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path("/opt/unsolved-channel/data/cases.db")

def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db() -> None:
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_key TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            case_name TEXT,
            country TEXT,
            case_type TEXT,
            case_status TEXT,
            incident_year INTEGER,
            article_url TEXT NOT NULL,
            source_name TEXT,
            published_at TEXT,
            article_summary TEXT,
            ai_summary TEXT,
            reason TEXT,
            mystery_score INTEGER DEFAULT 0,
            source_score INTEGER DEFAULT 0,
            storytelling_score INTEGER DEFAULT 0,
            audience_score INTEGER DEFAULT 0,
            safety_score INTEGER DEFAULT 0,
            overall_score INTEGER DEFAULT 0,
            is_suitable INTEGER DEFAULT 0,
            production_status TEXT DEFAULT 'NEW',
            raw_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_score ON cases(overall_score DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON cases(production_status)")

def existing_titles(limit: int = 2000) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT normalized_title FROM cases ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [r["normalized_title"] for r in rows]

def key_exists(case_key: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM cases WHERE case_key=? LIMIT 1", (case_key,)).fetchone()
    return row is not None

def insert_case(data: dict[str, Any]) -> int | None:
    cols = ", ".join(data.keys())
    marks = ", ".join("?" for _ in data)
    sql = f"INSERT OR IGNORE INTO cases ({cols}) VALUES ({marks})"
    with connect() as conn:
        cur = conn.execute(sql, tuple(data.values()))
        conn.commit()
        return int(cur.lastrowid) if cur.rowcount else None

def top_cases(limit: int = 20):
    with connect() as conn:
        return conn.execute("""
            SELECT * FROM cases
            WHERE is_suitable=1 AND production_status='NEW'
            ORDER BY overall_score DESC, created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
