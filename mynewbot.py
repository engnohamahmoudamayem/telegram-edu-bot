import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import asyncio

# ===================== ENV VARIABLES =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")     # لازم من Render
APP_URL = os.environ.get("APP_URL")         # مثال: https://mybot.onrender.com
PORT = int(os.environ.get("PORT", "10000")) # Render PORT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edu-bot")


# ===================== KEYBOARD =====================
def kb(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ===================== START HANDLER =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Webhook شغال 100%\nاختر من الأزرار:",
        reply_markup=kb([["اختبار", "رجوع"]])
    )


# ===================== MESSAGE HANDLER =====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "اختبار":
        return await update.message.reply_text("✔️ البوت شغال Webhook 100%")

    if text == "رجوع":
        return await start(update, context)

    await update.message.reply_text("❗ استخدمي الأزرار 👇")


# ===================== WEBHOOK MAIN =====================
async def main():
    if not BOT_TOKEN or not APP_URL:
        raise RuntimeError("❌ BOT_TOKEN أو APP_URL مش موجودين في Render")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🚀 Webhook server running...")

    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="/webhook",
        webhook_url=f"{APP_URL}/webhook"
    )


# ===================== RUN SCRIPT =====================
if __name__ == "__main__":
    asyncio.run(main())
