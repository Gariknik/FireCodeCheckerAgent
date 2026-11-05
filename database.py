import os
import sqlite3
import time
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "building_project.db")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS inspection_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    room_name TEXT NOT NULL,
    status TEXT CHECK(status IN ('PASSED', 'FAILED')),
    defects_count INTEGER DEFAULT 0,
    summary TEXT,
    model_used TEXT,
    tokens_prompt INTEGER DEFAULT 0,
    tokens_completion INTEGER DEFAULT 0,
    tokens_total INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Ініціалізує таблицю inspection_logs у базі даних SQLite."""
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        with conn:
            conn.execute(CREATE_TABLE_SQL)
    finally:
        conn.close()


def insert_inspection_log(
    chat_id: int,
    room_name: str,
    status: str,
    defects_count: int,
    summary: str,
    model_used: str,
    tokens_prompt: int,
    tokens_completion: int,
    estimated_cost_usd: float,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Зберігає лог аудиту та витрати токенів у БД SQLite building_project.db.
    Реалізує контроль РИЗИКУ 3: timeout=10.0 та retry loop до 3 спроб.
    """
    init_db(db_path)
    tokens_total = tokens_prompt + tokens_completion
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO inspection_logs (
                        chat_id, room_name, status, defects_count, summary,
                        model_used, tokens_prompt, tokens_completion,
                        tokens_total, estimated_cost_usd
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        room_name,
                        status,
                        defects_count,
                        summary,
                        model_used,
                        tokens_prompt,
                        tokens_completion,
                        tokens_total,
                        round(estimated_cost_usd, 6),
                    ),
                )
                log_id = cursor.lastrowid
            return {"log_id": log_id, "status": "SUCCESS"}
        except sqlite3.OperationalError as exc:
            if attempt == max_retries:
                return {"log_id": -1, "status": "ERROR", "error": str(exc)}
            time.sleep(0.5 * attempt)
        finally:
            conn.close()

    return {"log_id": -1, "status": "ERROR"}


def fetch_recent_logs(limit: int = 10, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Повертає останні записи з таблиці inspection_logs."""
    init_db(db_path)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT * FROM inspection_logs ORDER BY log_id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

