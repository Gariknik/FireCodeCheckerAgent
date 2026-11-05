import sys
import json
from agent import FireCodeCheckerAgent
from database import init_db, fetch_recent_logs

# Налаштування UTF-8 для консолі Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def run_demo_scenarios() -> None:
    # У локальному CLI-демо режимі вимикаємо реальну відправку на тестові chat_id (987654321..),
    # щоб не робити зайвих мережевих викликів до Telegram API
    import os
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
        print("=" * 85)
        print(f"▶ {title}")
        print("=" * 85)
        res = agent.run_react_inspection(chat_id=chat_id, message_text=msg)
        print("\n--- ReAct Trace ---")
        print(res["react_trace"])

        if res["success"]:
            print("\n--- Telegram Output (Pydantic FireSafetyReportOutput) ---")
            print(res["formatted_telegram_message"])
            print("\n--- Metrics & SQLite Log ---")
            print(json.dumps({"db_log": res["db_log"], "metrics": res["metrics"]}, ensure_ascii=False, indent=2))
        else:
            print("\n--- Повідомлення користувачу (ValidationError Control) ---")
            print(res["error"])
        print()

    print("=" * 85)
    print("📊 Вміст таблиці inspection_logs у SQLite (building_project.db):")
    print("=" * 85)
    logs = fetch_recent_logs(limit=6)
    print(json.dumps(logs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if "--bot" in sys.argv:
        from bot import run_telegram_bot
        run_telegram_bot()
    else:
        run_demo_scenarios()
