import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from agent import FireCodeCheckerAgent
from database import init_db

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

agent = FireCodeCheckerAgent()


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    welcome = (
        "👋 Вітаю! Я — інженерний AI-агент **FireCodeCheckerAgent** (аудитор норм ДБН В.1.1-7:2016).\n\n"
        "Надішліть параметри приміщення для перевірки, наприклад:\n"
        "`Перевірити приміщення: Складський комплекс, площа 250 кв.м, категорія В, кількість людей в приміщенні — 30, оздоблення стін — гіпсокартон Г1, відстань до виходу — 35м.`"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    user_text = update.message.text

    result = agent.run_react_inspection(chat_id=chat_id, message_text=user_text)
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("FireCodeCheckerAgent Telegram Bot запущено...")
    app.run_polling()


if __name__ == "__main__":
    run_telegram_bot()

