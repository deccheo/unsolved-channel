import sqlite3
from config import DB_PATH


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def migrate():
    with connect() as conn:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(cases)").fetchall()
        }

        additions = {
            "thumbnail_status": "TEXT DEFAULT 'PENDING'",
            "thumbnail_path": "TEXT",
            "thumbnail_created_at": "TEXT",
            "thumbnail_error": "TEXT",
        }

        for name, definition in additions.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE cases ADD COLUMN {name} {definition}"
                )


def candidate_cases(limit: int):
    with connect() as conn:
        return conn.execute("""
            SELECT c.*
            FROM cases c
            WHERE COALESCE(c.thumbnail_status, 'PENDING')
                  IN ('PENDING', 'RETRY')
              AND (
                    COALESCE(c.video_status, '') IN ('PREVIEW', 'READY')
                    OR EXISTS (
                        SELECT 1
                        FROM scenes s
                        WHERE s.case_id = c.id
                          AND s.image_status = 'READY'
                          AND COALESCE(s.image_path, '') <> ''
                    )
                  )
            ORDER BY
                COALESCE(c.verification_score, 0) DESC,
                COALESCE(c.overall_score, 0) DESC,
                c.id ASC
            LIMIT ?
        """, (limit,)).fetchall()


def best_scene_image(case_id: int):
    with connect() as conn:
        row = conn.execute("""
            SELECT image_path, visual_prompt, narration, scene_no
            FROM scenes
            WHERE case_id = ?
              AND image_status = 'READY'
              AND COALESCE(image_path, '') <> ''
            ORDER BY
                CASE visual_type
                    WHEN 'location_reconstruction' THEN 1
                    WHEN 'silhouette' THEN 2
                    WHEN 'evidence_object' THEN 3
                    ELSE 4
                END,
                scene_no ASC
            LIMIT 1
        """, (case_id,)).fetchone()

        return row


def mark_ready(case_id: int, path: str):
    with connect() as conn:
        conn.execute("""
            UPDATE cases
            SET thumbnail_status = 'READY',
                thumbnail_path = ?,
                thumbnail_created_at = CURRENT_TIMESTAMP,
                thumbnail_error = NULL
            WHERE id = ?
        """, (path, case_id))


def mark_retry(case_id: int, error: str):
    with connect() as conn:
        conn.execute("""
            UPDATE cases
            SET thumbnail_status = 'RETRY',
                thumbnail_error = ?
            WHERE id = ?
        """, (error[:2000], case_id))
