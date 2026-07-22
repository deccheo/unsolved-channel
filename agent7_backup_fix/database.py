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
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def migrate():
    with connect() as conn:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(cases)").fetchall()
        }
        for name, definition in CASE_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {name} {definition}")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                part_no INTEGER NOT NULL,
                start_scene INTEGER NOT NULL,
                end_scene INTEGER NOT NULL,
                scene_count INTEGER NOT NULL,
                path TEXT,
                duration REAL DEFAULT 0,
                status TEXT DEFAULT 'PENDING',
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(case_id, part_no),
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_video_parts_case ON video_parts(case_id, part_no)"
        )


def candidate_cases(limit: int):
    with connect() as conn:
        return conn.execute("""
            SELECT c.*
            FROM cases c
            WHERE COALESCE(c.video_status, 'PENDING')
                  IN ('PENDING', 'PARTIAL', 'PREVIEW', 'RETRY')
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
            "SELECT COUNT(*) FROM scenes WHERE case_id = ?", (case_id,)
        ).fetchone()[0])


def list_parts(case_id: int):
    with connect() as conn:
        return conn.execute("""
            SELECT * FROM video_parts
            WHERE case_id = ?
            ORDER BY part_no ASC
        """, (case_id,)).fetchall()


def save_part(
    case_id: int,
    part_no: int,
    start_scene: int,
    end_scene: int,
    scene_count: int,
    path: str,
    duration: float,
):
    with connect() as conn:
        conn.execute("""
            INSERT INTO video_parts(
                case_id, part_no, start_scene, end_scene, scene_count,
                path, duration, status, error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DONE', NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(case_id, part_no) DO UPDATE SET
                start_scene=excluded.start_scene,
                end_scene=excluded.end_scene,
                scene_count=excluded.scene_count,
                path=excluded.path,
                duration=excluded.duration,
                status='DONE',
                error=NULL,
                updated_at=CURRENT_TIMESTAMP
        """, (
            case_id, part_no, start_scene, end_scene, scene_count, path, duration
        ))
        conn.execute("""
            UPDATE cases
            SET video_status='PARTIAL',
                video_error=NULL
            WHERE id=? AND COALESCE(video_status, 'PENDING') <> 'READY'
        """, (case_id,))


def mark_part_retry(case_id: int, part_no: int, start_scene: int, end_scene: int, error: str):
    with connect() as conn:
        conn.execute("""
            INSERT INTO video_parts(
                case_id, part_no, start_scene, end_scene, scene_count,
                status, error, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'RETRY', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(case_id, part_no) DO UPDATE SET
                status='RETRY',
                error=excluded.error,
                updated_at=CURRENT_TIMESTAMP
        """, (
            case_id, part_no, start_scene, end_scene,
            max(0, end_scene - start_scene + 1), error[:2000]
        ))
        conn.execute("""
            UPDATE cases SET video_status='RETRY', video_error=? WHERE id=?
        """, (error[:2000], case_id))


def save_video(case_id: int, path: str, duration: float, scene_count: int, complete: bool):
    status = "READY" if complete else "PARTIAL"
    production_status = "VIDEO_READY" if complete else "SCENED"
    with connect() as conn:
        conn.execute("""
            UPDATE cases
            SET video_status=?, video_path=?, video_duration=?,
                video_scene_count=?, video_created_at=CURRENT_TIMESTAMP,
                video_error=NULL, production_status=?
            WHERE id=?
        """, (
            status, path, duration, scene_count, production_status, case_id
        ))


def mark_retry(case_id: int, error: str):
    with connect() as conn:
        conn.execute("""
            UPDATE cases SET video_status='RETRY', video_error=? WHERE id=?
        """, (error[:2000], case_id))
