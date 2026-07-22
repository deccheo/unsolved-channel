import sqlite3
from config import DB_PATH


CASE_COLUMNS = {
    "video_status": "TEXT DEFAULT 'PENDING'",
    "video_path": "TEXT",
    "video_duration": "REAL DEFAULT 0",
    "video_scene_count": "INTEGER DEFAULT 0",
    "video_created_at": "TEXT",
    "video_error": "TEXT",
}


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def migrate():
    with connect() as conn:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(cases)").fetchall()
        }

        for name, definition in CASE_COLUMNS.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE cases ADD COLUMN {name} {definition}"
                )


def candidate_cases(limit: int):
    with connect() as conn:
        return conn.execute("""
            SELECT c.*
            FROM cases c
            WHERE COALESCE(c.video_status, 'PENDING')
                  IN ('PENDING', 'PREVIEW', 'RETRY')
              AND EXISTS (
                  SELECT 1
                  FROM scenes s
                  WHERE s.case_id = c.id
                    AND s.image_status = 'READY'
                    AND s.audio_status = 'READY'
                    AND COALESCE(s.image_path, '') <> ''
                    AND COALESCE(s.audio_path, '') <> ''
              )
            ORDER BY
                COALESCE(c.verification_score, 0) DESC,
                COALESCE(c.overall_score, 0) DESC,
                c.id ASC
            LIMIT ?
        """, (limit,)).fetchall()


def ready_scenes(case_id: int):
    with connect() as conn:
        return conn.execute("""
            SELECT *
            FROM scenes
            WHERE case_id = ?
              AND image_status = 'READY'
              AND audio_status = 'READY'
              AND COALESCE(image_path, '') <> ''
              AND COALESCE(audio_path, '') <> ''
            ORDER BY scene_no ASC
        """, (case_id,)).fetchall()


def total_scene_count(case_id: int) -> int:
    with connect() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM scenes WHERE case_id = ?",
            (case_id,),
        ).fetchone()[0])


def save_video(
    case_id: int,
    path: str,
    duration: float,
    scene_count: int,
    complete: bool,
):
    status = "READY" if complete else "PREVIEW"
    production_status = "VIDEO_READY" if complete else "SCENED"

    with connect() as conn:
        conn.execute("""
            UPDATE cases
            SET video_status = ?,
                video_path = ?,
                video_duration = ?,
                video_scene_count = ?,
                video_created_at = CURRENT_TIMESTAMP,
                video_error = NULL,
                production_status = ?
            WHERE id = ?
        """, (
            status,
            path,
            duration,
            scene_count,
            production_status,
            case_id,
        ))


def mark_retry(case_id: int, error: str):
    with connect() as conn:
        conn.execute("""
            UPDATE cases
            SET video_status = 'RETRY',
                video_error = ?
            WHERE id = ?
        """, (error[:2000], case_id))


def reset_renderable_cases():
    with connect() as conn:
        conn.execute("""
            UPDATE cases
            SET video_status = 'PENDING',
                video_error = NULL
            WHERE id IN (
                SELECT DISTINCT case_id
                FROM scenes
                WHERE image_status = 'READY'
                  AND audio_status = 'READY'
                  AND COALESCE(image_path, '') <> ''
                  AND COALESCE(audio_path, '') <> ''
            )
        """)
