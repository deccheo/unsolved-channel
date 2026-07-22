import sqlite3
from config import DB_PATH


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def migrate():
    with connect() as conn:
        case_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(cases)").fetchall()
        }
        case_additions = {
            "voice_status": "TEXT DEFAULT 'PENDING'",
            "voice_count": "INTEGER DEFAULT 0",
            "voice_created_at": "TEXT",
        }
        for name, definition in case_additions.items():
            if name not in case_cols:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {name} {definition}")

        scene_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(scenes)").fetchall()
        }
        scene_additions = {
            "audio_path": "TEXT",
            "audio_status": "TEXT DEFAULT 'PENDING'",
            "audio_duration": "REAL DEFAULT 0",
            "audio_error": "TEXT",
            "audio_attempts": "INTEGER DEFAULT 0",
        }
        for name, definition in scene_additions.items():
            if name not in scene_cols:
                conn.execute(f"ALTER TABLE scenes ADD COLUMN {name} {definition}")


def pending_cases(limit: int):
    with connect() as conn:
        return conn.execute("""
            SELECT * FROM cases
            WHERE scene_status='READY'
              AND COALESCE(voice_status,'PENDING')
                  IN ('PENDING','PARTIAL','RETRY')
            ORDER BY verification_score DESC, overall_score DESC
            LIMIT ?
        """, (limit,)).fetchall()


def pending_scenes(case_id: int, limit: int):
    with connect() as conn:
        return conn.execute("""
            SELECT * FROM scenes
            WHERE case_id=?
              AND COALESCE(audio_status,'PENDING')
                  IN ('PENDING','RETRY')
            ORDER BY scene_no ASC
            LIMIT ?
        """, (case_id, limit)).fetchall()


def find_cached_audio(narration: str, exclude_scene_id: int):
    normalized = " ".join((narration or "").split())
    if not normalized:
        return None
    with connect() as conn:
        return conn.execute("""
            SELECT id, audio_path, audio_duration
            FROM scenes
            WHERE id <> ?
              AND TRIM(COALESCE(narration,'')) = ?
              AND audio_status='READY'
              AND COALESCE(audio_path,'') <> ''
            ORDER BY id DESC
            LIMIT 1
        """, (exclude_scene_id, normalized)).fetchone()


def mark_scene_ready(scene_id: int, path: str, duration: float, attempts: int = 1):
    with connect() as conn:
        conn.execute("""
            UPDATE scenes SET
                audio_path=?,
                audio_status='READY',
                audio_duration=?,
                audio_error=NULL,
                audio_attempts=COALESCE(audio_attempts,0)+?
            WHERE id=?
        """, (path, duration, attempts, scene_id))


def mark_scene_cached(scene_id: int, path: str, duration: float):
    with connect() as conn:
        conn.execute("""
            UPDATE scenes SET
                audio_path=?,
                audio_status='READY',
                audio_duration=?,
                audio_error=NULL
            WHERE id=?
        """, (path, duration, scene_id))


def mark_scene_retry(scene_id: int, error: str, attempts: int = 1):
    with connect() as conn:
        conn.execute("""
            UPDATE scenes SET
                audio_status='RETRY',
                audio_error=?,
                audio_attempts=COALESCE(audio_attempts,0)+?
            WHERE id=?
        """, (error[:1200], attempts, scene_id))


def finalize_case(case_id: int):
    with connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM scenes WHERE case_id=?", (case_id,)
        ).fetchone()[0]
        ready = conn.execute("""
            SELECT COUNT(*) FROM scenes
            WHERE case_id=? AND audio_status='READY'
        """, (case_id,)).fetchone()[0]

        if total > 0 and ready == total:
            status = "READY"
        elif ready > 0:
            status = "PARTIAL"
        else:
            status = "RETRY"

        conn.execute("""
            UPDATE cases SET
                voice_status=?,
                voice_count=?,
                voice_created_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (status, ready, case_id))
