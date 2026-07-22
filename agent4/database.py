from __future__ import annotations

import json
import sqlite3
from typing import Any

from .config import DB_PATH, MAX_RETRIES

CASE_COLUMNS = {
    "scene_status": "TEXT DEFAULT 'PENDING'",
    "scene_count": "INTEGER DEFAULT 0",
    "scene_qa_score": "INTEGER DEFAULT 0",
    "scene_retry_count": "INTEGER DEFAULT 0",
    "scene_error": "TEXT",
    "scene_created_at": "TEXT",
}

SCENE_COLUMNS = {
    "case_id": "INTEGER",
    "scene_no": "INTEGER",
    "narration": "TEXT",
    "visual_prompt": "TEXT",
    "negative_prompt": "TEXT",
    "duration_seconds": "REAL DEFAULT 0",
    "transition": "TEXT",
    "camera_direction": "TEXT",
    "location": "TEXT",
    "time_period": "TEXT",
    "characters_json": "TEXT DEFAULT '[]'",
    "continuity_key": "TEXT",
    "source_claims_json": "TEXT DEFAULT '[]'",
    "prompt_version": "TEXT",
    "scene_status": "TEXT DEFAULT 'READY'",
    "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
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
        tables = {
            str(r["name"])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "cases" not in tables:
            raise RuntimeError("Không tìm thấy bảng cases; dừng để tránh tạo sai pipeline")

        case_cols = _columns(conn, "cases")
        for name, definition in CASE_COLUMNS.items():
            if name not in case_cols:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {name} {definition}")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                scene_no INTEGER NOT NULL,
                narration TEXT NOT NULL,
                visual_prompt TEXT NOT NULL,
                negative_prompt TEXT,
                duration_seconds REAL DEFAULT 0,
                transition TEXT,
                camera_direction TEXT,
                location TEXT,
                time_period TEXT,
                characters_json TEXT DEFAULT '[]',
                continuity_key TEXT,
                source_claims_json TEXT DEFAULT '[]',
                prompt_version TEXT,
                scene_status TEXT DEFAULT 'READY',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(case_id, scene_no),
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            )
        """)

        scene_cols = _columns(conn, "scenes")
        for name, definition in SCENE_COLUMNS.items():
            if name not in scene_cols:
                conn.execute(f"ALTER TABLE scenes ADD COLUMN {name} {definition}")

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_scenes_case_no
            ON scenes(case_id, scene_no)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent4_queue
            ON cases(production_status, script_status, scene_status, overall_score)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_scenes_case_status
            ON scenes(case_id, scene_status, scene_no)
        """)

def assert_schema() -> None:
    with connect() as conn:
        case_cols = _columns(conn, "cases")
        missing_cases = set(CASE_COLUMNS) - case_cols
        if missing_cases:
            raise RuntimeError(f"Schema cases thiếu: {sorted(missing_cases)}")

        scene_cols = _columns(conn, "scenes")
        required_scenes = {
            "id", "case_id", "scene_no", "narration", "visual_prompt",
            "duration_seconds", "scene_status"
        }
        missing_scenes = required_scenes - scene_cols
        if missing_scenes:
            raise RuntimeError(f"Schema scenes thiếu: {sorted(missing_scenes)}")

def pending_cases(limit: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("""
            SELECT *
            FROM cases
            WHERE COALESCE(production_status,'') = 'SCRIPTED'
              AND COALESCE(script_status,'APPROVED') = 'APPROVED'
              AND length(trim(COALESCE(script_text,''))) > 0
              AND COALESCE(scene_status,'PENDING') IN ('PENDING','RETRY')
              AND COALESCE(scene_retry_count,0) < ?
            ORDER BY COALESCE(script_qa_score,0) DESC,
                     COALESCE(verification_score,0) DESC,
                     COALESCE(overall_score,0) DESC,
                     id ASC
            LIMIT ?
        """, (MAX_RETRIES, limit)).fetchall()

def script_claims_for(case_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        tables = {
            str(r["name"])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "script_claims" not in tables:
            return []
        rows = conn.execute("""
            SELECT claim_text, source_urls, confidence
            FROM script_claims
            WHERE case_id=?
            ORDER BY id ASC
        """, (case_id,)).fetchall()

    output: list[dict[str, Any]] = []
    for row in rows:
        try:
            urls = json.loads(row["source_urls"] or "[]")
        except Exception:
            urls = []
        output.append({
            "claim": str(row["claim_text"] or ""),
            "source_urls": urls if isinstance(urls, list) else [],
            "confidence": str(row["confidence"] or "MEDIUM"),
        })
    return output

def replace_scenes(
    case_id: int,
    scenes: list[dict[str, Any]],
    qa_score: int,
) -> None:
    if not scenes:
        raise ValueError("Không được lưu danh sách cảnh trống")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM scenes WHERE case_id=?", (case_id,))

        for scene in scenes:
            conn.execute("""
                INSERT INTO scenes (
                    case_id, scene_no, narration, visual_prompt,
                    negative_prompt, duration_seconds, transition,
                    camera_direction, location, time_period,
                    characters_json, continuity_key, source_claims_json,
                    prompt_version, scene_status
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                case_id,
                int(scene["scene_no"]),
                str(scene["narration"]).strip(),
                str(scene["visual_prompt"]).strip(),
                str(scene.get("negative_prompt", "")).strip(),
                float(scene.get("duration_seconds", 0) or 0),
                str(scene.get("transition", "cut")).strip(),
                str(scene.get("camera_direction", "")).strip(),
                str(scene.get("location", "")).strip(),
                str(scene.get("time_period", "")).strip(),
                json.dumps(scene.get("characters", []), ensure_ascii=False),
                str(scene.get("continuity_key", "")).strip(),
                json.dumps(scene.get("source_claims", []), ensure_ascii=False),
                str(scene.get("prompt_version", "")).strip(),
                "READY",
            ))

        conn.execute("""
            UPDATE cases SET
                scene_status='READY',
                scene_count=?,
                scene_qa_score=?,
                scene_retry_count=0,
                scene_error=NULL,
                scene_created_at=CURRENT_TIMESTAMP,
                production_status='SCENED'
            WHERE id=?
        """, (len(scenes), int(qa_score), case_id))

def mark_review(case_id: int, reason: str) -> None:
    with connect() as conn:
        conn.execute("""
            UPDATE cases SET
                scene_status='NEEDS_REVIEW',
                scene_error=?
            WHERE id=?
        """, (reason[:2000], case_id))

def mark_retry(case_id: int, reason: str) -> None:
    with connect() as conn:
        conn.execute("""
            UPDATE cases SET
                scene_status=CASE
                    WHEN COALESCE(scene_retry_count,0)+1 >= ? THEN 'FAILED'
                    ELSE 'RETRY'
                END,
                scene_retry_count=COALESCE(scene_retry_count,0)+1,
                scene_error=?
            WHERE id=?
        """, (MAX_RETRIES, reason[:2000], case_id))
