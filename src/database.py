import json
import os
import sqlite3
import time
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from src.console_style import Style

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


def fetch_recent_logs(
    limit: int = 10,
    status_filter: Optional[str] = None,
    chat_id_filter: Optional[int] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Повертає записи з таблиці inspection_logs із підтримкою фільтрації за статусом та chat_id."""
    init_db(db_path)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row

    clauses: List[str] = []
    params: List[Any] = []

    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter.upper())
    if chat_id_filter is not None:
        clauses.append("chat_id = ?")
        params.append(chat_id_filter)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM inspection_logs {where_sql} ORDER BY log_id DESC LIMIT ?"
    params.append(limit)

    try:
        cursor = conn.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def fetch_db_summary_stats(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Повертає загальну статистику перевірок та витрат токенів у БД SQLite."""
    init_db(db_path)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            """
            SELECT
                COUNT(*) AS total_inspections,
                SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) AS passed_count,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_count,
                COALESCE(SUM(tokens_total), 0) AS total_tokens,
                ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6) AS total_cost_usd
            FROM inspection_logs
            """
        )
        row = cursor.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def format_logs_for_console(
    logs: List[Dict[str, Any]],
    stats: Optional[Dict[str, Any]] = None,
    as_json: bool = False,
) -> str:
    """Формує наглядне табличне або JSON представлення логів БД для виводу в консоль."""
    if as_json:
        return json.dumps({"stats": stats, "logs": logs}, ensure_ascii=False, indent=2)

    lines: List[str] = []
    sep = f"{Style.BOLD}{Style.BLUE}{'=' * 114}{Style.RESET}"
    sub_sep = f"{Style.GRAY}{'-' * 114}{Style.RESET}"
    lines.append(sep)
    lines.append(f"{Style.BOLD}{Style.CYAN}📊 ЖУРНАЛ ПЕРЕВІРОК З БАЗИ ДАНИХ SQLite (inspection_logs){Style.RESET}")
    lines.append(sep)

    if stats:
        lines.append(
            f"{Style.BOLD}Всього перевірок:{Style.RESET} {Style.BOLD}{Style.WHITE}{stats.get('total_inspections', 0)}{Style.RESET} | "
            f"{Style.BOLD}{Style.GREEN}🟢 PASSED: {stats.get('passed_count') or 0}{Style.RESET} | "
            f"{Style.BOLD}{Style.RED}🔴 FAILED: {stats.get('failed_count') or 0}{Style.RESET} | "
            f"{Style.BOLD}Токенів загалом:{Style.RESET} {Style.CYAN}{stats.get('total_tokens', 0)}{Style.RESET} | "
            f"{Style.BOLD}Витрати:{Style.RESET} {Style.YELLOW}${stats.get('total_cost_usd', 0.0):.6f}{Style.RESET}"
        )
        lines.append(sub_sep)

    if not logs:
        lines.append(f"{Style.YELLOW}Записів за вказаними критеріями не знайдено.{Style.RESET}")
        return "\n".join(lines)

    header = (
        f"{Style.BOLD}{Style.WHITE}"
        f"{'ID':<4} | {'Час (UTC)':<19} | {'Chat ID':<10} | {'Статус':<6} | {'Деф.':<4} | {'Токени':<6} | {'Вартість $':<10} | {'Приміщення'}"
        f"{Style.RESET}"
    )
    lines.append(header)
    lines.append(sub_sep)

    for row in logs:
        raw_status = row["status"]
        if raw_status == "PASSED":
            status_col = f"{Style.BOLD}{Style.GREEN}{'PASSED':<6}{Style.RESET}"
        else:
            status_col = f"{Style.BOLD}{Style.RED}{'FAILED':<6}{Style.RESET}"

        lines.append(
            f"{Style.BOLD}{row['log_id']:<4}{Style.RESET} | "
            f"{Style.GRAY}{str(row['timestamp']):<19}{Style.RESET} | "
            f"{Style.CYAN}{row['chat_id']:<10}{Style.RESET} | "
            f"{status_col} | "
            f"{row['defects_count']:<4} | "
            f"{Style.CYAN}{row['tokens_total']:<6}{Style.RESET} | "
            f"{Style.YELLOW}${row['estimated_cost_usd']:<9.6f}{Style.RESET} | "
            f"{Style.BOLD}{Style.WHITE}{row['room_name']}{Style.RESET}"
        )
        if row.get("summary"):
            short_sum = row["summary"] if len(row["summary"]) <= 95 else row["summary"][:92] + "..."
            lines.append(f"     {Style.GRAY}└─ Підсумок: {short_sum}{Style.RESET}")

    lines.append(sep)
    return "\n".join(lines)

