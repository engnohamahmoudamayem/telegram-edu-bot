import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
import asyncio

# -------- ENV VARIABLES FROM RENDER --------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")  # https://your-service.onrender.com
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edu-bot")


def kb(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# -------- MENUS --------
MENU_DATA = {
    "main": {
        "text": "منصة تعليمية لطلاب جميع المراحل\n\nمن فضلك اختر المرحلة:",
        "buttons": [["الثانوية", "المتوسطة", "الابتدائية"], ["روابط مهمة"]],
    }
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        MENU_DATA["main"]["text"],
        reply_markup=kb(MENU_DATA["main"]["buttons"])
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("البوت يعمل الآن ✔️")


# -------- MAIN (WEBHOOK MODE) --------
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Webhook mode
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{APP_URL}/webhook"
    )


if __name__ == "__main__":
    asyncio.run(main())
