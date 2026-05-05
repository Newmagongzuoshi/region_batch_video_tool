import os
import sqlite3
import json
import csv
from datetime import datetime

from utils.path_utils import resolve_data_path
from utils.logger import get_logger

logger = get_logger()

DB_PATH = resolve_data_path("cache", "task_state.sqlite")


class TaskStore:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or DB_PATH
        if self._db_path != ":memory:":
            db_dir = os.path.dirname(self._db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        if self._db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                region TEXT NOT NULL,
                safe_filename TEXT NOT NULL,
                gif_status TEXT NOT NULL DEFAULT 'pending',
                mp3_status TEXT NOT NULL DEFAULT 'pending',
                mp4_status TEXT NOT NULL DEFAULT 'pending',
                gif_path TEXT,
                mp3_path TEXT,
                mp4_path TEXT,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_video_path TEXT,
                source_gif_path TEXT,
                region_txt_path TEXT,
                output_dir TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()

    def create_run(self, video_path: str, gif_path: str, txt_path: str, output_dir: str) -> int:
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO app_runs (source_video_path, source_gif_path, region_txt_path, output_dir, created_at) VALUES (?,?,?,?,?)",
            (video_path, gif_path, txt_path, output_dir, datetime.now().isoformat())
        )
        conn.commit()
        return cur.lastrowid

    def create_tasks(self, regions: list[dict]) -> int:
        now = datetime.now().isoformat()
        conn = self._get_conn()
        count = 0
        for r in regions:
            conn.execute(
                "INSERT INTO tasks (region, safe_filename, created_at, updated_at) VALUES (?,?,?,?)",
                (r["region"], r["safe_filename"], now, now)
            )
            count += 1
        conn.commit()
        logger.info(f"Created {count} tasks")
        return count

    def update_task_status(self, task_id: int, field: str, status: str,
                           path: str | None = None, error: str | None = None):
        now = datetime.now().isoformat()
        conn = self._get_conn()
        if field == "gif":
            conn.execute(
                "UPDATE tasks SET gif_status=?, gif_path=?, error_message=?, updated_at=? WHERE id=?",
                (status, path, error, now, task_id)
            )
        elif field == "mp3":
            conn.execute(
                "UPDATE tasks SET mp3_status=?, mp3_path=?, error_message=?, updated_at=? WHERE id=?",
                (status, path, error, now, task_id)
            )
        elif field == "mp4":
            conn.execute(
                "UPDATE tasks SET mp4_status=?, mp4_path=?, error_message=?, updated_at=? WHERE id=?",
                (status, path, error, now, task_id)
            )
        conn.commit()

    def increment_retry(self, task_id: int):
        conn = self._get_conn()
        conn.execute(
            "UPDATE tasks SET retry_count = retry_count + 1, updated_at=? WHERE id=?",
            (datetime.now().isoformat(), task_id)
        )
        conn.commit()

    def get_task(self, task_id: int) -> dict | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def get_all_tasks(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def get_failed_tasks(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM tasks WHERE gif_status='failed' OR mp3_status='failed' OR mp4_status='failed' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_pending_tasks(self, step: str) -> list[dict]:
        field = f"{step}_status"
        conn = self._get_conn()
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE {field} IN ('pending', 'failed') ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_event(self, task_id: int, level: str, message: str):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO task_events (task_id, level, message, created_at) VALUES (?,?,?,?)",
            (task_id, level, message, datetime.now().isoformat())
        )
        conn.commit()

    def export_failed_json(self, output_path: str) -> str:
        failed = self.get_failed_tasks()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(failed, f, ensure_ascii=False, indent=2)
        logger.info(f"Exported {len(failed)} failed tasks to {output_path}")
        return output_path

    def export_batch_csv(self, output_path: str) -> str:
        tasks = self.get_all_tasks()
        if not tasks:
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["id", "region", "gif_status", "mp3_status", "mp4_status",
                                 "error_message", "retry_count", "updated_at"])
            return output_path

        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(tasks[0].keys())
            for t in tasks:
                writer.writerow(t.values())
        logger.info(f"Exported {len(tasks)} task rows to {output_path}")
        return output_path

    def get_stats(self) -> dict:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) as c FROM tasks").fetchone()["c"]
        completed = conn.execute(
            "SELECT COUNT(*) as c FROM tasks WHERE gif_status='completed' AND mp3_status='completed' AND mp4_status='completed'"
        ).fetchone()["c"]
        failed = conn.execute(
            "SELECT COUNT(*) as c FROM tasks WHERE gif_status='failed' OR mp3_status='failed' OR mp4_status='failed'"
        ).fetchone()["c"]
        pending = total - completed - failed
        return {"total": total, "completed": completed, "failed": failed, "pending": max(0, pending)}
