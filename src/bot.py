import os
import sys
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from src.agent import FireCodeCheckerAgent
from src.database import init_db, fetch_recent_logs, fetch_db_summary_stats, format_logs_for_console

load_dotenv()

# Налаштування UTF-8 для консолі Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Вимикаємо службовий шум httpx/telegram, щоб під час запиту в консоль виводився тільки ReAct Trace
logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

agent = FireCodeCheckerAgent()


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    welcome = (
        "👋 Вітаю! Я — інженерний AI-агент **FireCodeCheckerAgent** (аудитор норм ДБН В.1.1-7:2016).\n\n"
        "Надішліть параметри приміщення для перевірки, наприклад:\n"
        "`Перевірити приміщення: Складський комплекс, площа 250 кв.м, категорія В, кількість людей в приміщенні — 30, оздоблення стін — гіпсокартон Г1, відстань до виходу — 35м.`\n\n"
        "Команди:\n"
        "• `/start` — довідка та шаблон\n"
        "• `/logs` — переглянути останні 5 записів перевірок у БД"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /logs — виводить останні записи з бази даних у консоль та в чат."""
    if not update.message:
        return
    logs = fetch_recent_logs(limit=5, chat_id_filter=update.message.chat_id)
    stats = fetch_db_summary_stats()
    print(format_logs_for_console(logs, stats=stats), flush=True)

    if not logs:
        await update.message.reply_text("📭 У базі даних ще немає записів для цього чату.")
        return

    lines = ["📊 Останні перевірки з БД SQLite:"]
    for row in logs:
        icon = "🟢" if row["status"] == "PASSED" else "🔴"
        lines.append(
            f"{icon} #{row['log_id']} | {row['room_name']} — {row['status']} "
            f"(порушень: {row['defects_count']}, токенів: {row['tokens_total']})"
        )
    await update.message.reply_text("\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    user_text = update.message.text

    # Під час запиту в консоль у реальному часі виводиться тільки ReAct Trace (print_trace=True)
    result = agent.run_react_inspection(
        chat_id=chat_id,
        message_text=user_text,
        print_trace=True,
    )
    if not result["success"]:
        await update.message.reply_text(result["error"])
        return

    # Інструмент send_telegram_report вже відправляє повідомлення через Telegram API.
    # Відправляємо через reply_text лише якщо інструмент не доставив його напряму.
    if not result.get("delivered_via_api", False):
        try:
            await update.message.reply_text(
                result["formatted_telegram_message"],
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception:
            await update.message.reply_text(
                result["formatted_telegram_message"].replace(r"\_", "_"),
                disable_web_page_preview=True,
            )


def run_telegram_bot() -> None:
    init_db()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token or token == "YOUR_BOT_TOKEN":
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не налаштовано у .env. Вкажіть дійсний токен Telegram-бота."
        )
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("logs", logs_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    run_telegram_bot()
