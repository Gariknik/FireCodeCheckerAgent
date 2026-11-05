import argparse
import os
import sys
import json
from typing import Optional

from src.agent import FireCodeCheckerAgent
from src.console_style import Style, colorize_react_block
from src.database import (
    init_db,
    fetch_recent_logs,
    fetch_db_summary_stats,
    format_logs_for_console,
)

# Налаштування UTF-8 для консолі Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def show_logs_in_console(
    limit: int = 10,
    status_filter: Optional[str] = None,
    chat_id_filter: Optional[int] = None,
    as_json: bool = False,
) -> None:
    """Отримує та виводить логи перевірок із БД SQLite у консоль."""
    logs = fetch_recent_logs(
        limit=limit,
        status_filter=status_filter,
        chat_id_filter=chat_id_filter,
    )
    stats = fetch_db_summary_stats()
    print(format_logs_for_console(logs=logs, stats=stats, as_json=as_json))


def run_demo_scenarios() -> None:
    """Запускає набір із 6 демонстраційних сценаріїв перевірки ДБН В.1.1-7:2016."""
    os.environ["TELEGRAM_BOT_TOKEN"] = "YOUR_BOT_TOKEN"
    init_db()
    agent = FireCodeCheckerAgent()

    scenarios = [
        (
            987654321,
            "Перевірити приміщення: Складський комплекс, площа 250 кв.м, категорія В, оздоблення стін — гіпсокартон Г1, відстань до виходу — 35м.",
            "СЦЕНАРІЙ 1 (FAILED — базовий ReAct Trace з перефразуванням запиту)",
        ),
        (
            987654322,
            "Перевірити приміщення: Серверна кімната, площа 45 кв.м, категорія В, кількість людей в приміщенні — 5, оздоблення стін — Г1, відстань до виходу — 12м, ширина дверей 0.9м, висота дверей 2.1м, назовні.",
            "СЦЕНАРІЙ 2 (PASSED — повна відповідність нормам ДБН В.1.1-7:2016)",
        ),
        (
            987654323,
            "Перевірити приміщення: Офіс 302 (без категорії), площа 60 кв.м, кількість людей в приміщенні — 20 осіб, оздоблення стін — Г1, відстань до виходу — 18м, двері 0.9х2.1м, назовні.",
            "СЦЕНАРІЙ 3 (PASSED — приміщення без категорії + кількість людей + компактний розмір дверей)",
        ),
        (
            987654324,
            "Перевірити приміщення: Конференц-зал, площа 70 кв.м, кількість людей в приміщенні — 60 осіб, 1 вихід, двері 0.9х2.0м, всередину, відстань до виходу — 20м.",
            "СЦЕНАРІЙ 4 (FAILED — порушення норм для >50 людей: щільність, ширина дверей <1.2м, 1 вихід, двері всередину)",
        ),
        (
            987654325,
            "Перевірити приміщення: Дільниця фарбування, площа 120 кв.м, категорія А, висота стелі 1.85м, оздоблення стін — пластик Г3, відстань до виходу — 22м, двері 0.8х1.85м, виходів 1.",
            "СЦЕНАРІЙ 5 (FAILED — категорія А: порушення відстані >15м, оздоблення Г3, висоти стелі та дверей <2.0м, 1 вихід при >100м²)",
        ),
        (
            987654326,
            "Перевірити приміщення без площі",
            "СЦЕНАРІЙ 6 (ValidationError — перевірка контролю РИЗИКУ 1)",
        ),
    ]

    for chat_id, msg, title in scenarios:
        print(f"{Style.BOLD}{Style.BLUE}{'=' * 95}{Style.RESET}")
        print(f"{Style.BG_BLUE} ▶ {title} {Style.RESET}")
        print(f"{Style.BOLD}{Style.BLUE}{'=' * 95}{Style.RESET}")
        res = agent.run_react_inspection(chat_id=chat_id, message_text=msg)
        print(f"\n{Style.BOLD}{Style.MAGENTA}─── ReAct Trace ───{Style.RESET}")
        print(colorize_react_block(res["react_trace"]))

        if res["success"]:
            print("\n--- Telegram Output (Pydantic FireSafetyReportOutput) ---")
            print(res["formatted_telegram_message"])
            print("\n--- Metrics & SQLite Log ---")
            print(json.dumps({"db_log": res["db_log"], "metrics": res["metrics"]}, ensure_ascii=False, indent=2))
        else:
            print("\n--- Повідомлення користувачу (ValidationError Control) ---")
            print(res["error"])
        print()

    show_logs_in_console(limit=6)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FireCodeCheckerAgent — інженерний AI-агент аудиту норм ДБН В.1.1-7:2016"
    )
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Запустити Telegram-бота у режимі polling (під час запитів виводить у консоль тільки ReAct Trace)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Виконати перевірку одного запиту і вивести у консоль тільки ReAct Trace",
    )
    parser.add_argument(
        "--logs",
        action="store_true",
        help="Вивести у консоль журнал перевірок та статистику з бази даних SQLite",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Кількість останніх записів для виводу з БД (за замовчуванням: 15)",
    )
    parser.add_argument(
        "--status",
        choices=["PASSED", "FAILED", "passed", "failed"],
        default=None,
        help="Фільтр логів за статусом перевірки (PASSED або FAILED)",
    )
    parser.add_argument(
        "--chat-id",
        type=int,
        default=None,
        help="Фільтр логів за конкретним Telegram chat_id",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вивести логи з БД у форматі JSON замість таблиці",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.bot:
        from src.bot import run_telegram_bot
        run_telegram_bot()
    elif args.query:
        os.environ["TELEGRAM_BOT_TOKEN"] = "YOUR_BOT_TOKEN"
        init_db()
        FireCodeCheckerAgent().run_react_inspection(
            chat_id=987654321,
            message_text=args.query,
            print_trace=True,
        )
    elif args.logs:
        show_logs_in_console(
            limit=args.limit,
            status_filter=args.status,
            chat_id_filter=args.chat_id,
            as_json=args.json,
        )
    else:
        run_demo_scenarios()
