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
            "scene_status": "TEXT DEFAULT 'PENDING'",
            "scene_count": "INTEGER DEFAULT 0",
            "scene_created_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {name} {definition}")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS scenes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            scene_no INTEGER NOT NULL,
            narration TEXT NOT NULL,
            duration_seconds REAL DEFAULT 8,
            visual_type TEXT,
            visual_prompt TEXT,
            on_screen_text TEXT,
            source_note TEXT,
            disclaimer_label TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(case_id, scene_no),
            FOREIGN KEY(case_id) REFERENCES cases(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scenes_case ON scenes(case_id, scene_no)")

def pending_cases(limit: int):
    with connect() as conn:
        return conn.execute("""
            SELECT * FROM cases
            WHERE production_status='SCRIPTED'
              AND COALESCE(scene_status,'PENDING') IN ('PENDING','RETRY')
            ORDER BY verification_score DESC, overall_score DESC
            LIMIT ?
        """, (limit,)).fetchall()

def save_scenes(case_id: int, scenes: list[dict]):
    with connect() as conn:
        conn.execute("DELETE FROM scenes WHERE case_id=?", (case_id,))
        for scene in scenes:
            conn.execute("""
                INSERT INTO scenes(
                    case_id, scene_no, narration, duration_seconds,
                    visual_type, visual_prompt, on_screen_text,
                    source_note, disclaimer_label
                ) VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                case_id,
                scene.get("scene_no"),
                scene.get("narration",""),
                scene.get("duration_seconds",8),
                scene.get("visual_type",""),
                scene.get("visual_prompt",""),
                scene.get("on_screen_text",""),
                scene.get("source_note",""),
                scene.get("disclaimer_label",""),
            ))

        conn.execute("""
            UPDATE cases SET
                scene_status='READY',
                scene_count=?,
                scene_created_at=CURRENT_TIMESTAMP,
                production_status='SCENED'
            WHERE id=?
        """, (len(scenes), case_id))

def mark_retry(case_id: int):
    with connect() as conn:
        conn.execute("""
            UPDATE cases SET scene_status='RETRY'
            WHERE id=?
        """, (case_id,))
