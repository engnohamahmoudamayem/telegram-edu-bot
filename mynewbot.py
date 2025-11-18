import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import asyncio

# ===================== ENV VARS ======================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")      # مثال: https://telegram-edu-bot.onrender.com
PORT = int(os.environ.get("PORT", "10000"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edu-bot")

# ===================== KEYBOARD ======================
def kb(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ===================== HANDLERS ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✔️ Bot is running on Render\nاختر أمراً:",
        reply_markup=kb([["اختبار", "رجوع"]])
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "اختبار":
        return await update.message.reply_text("🚀 البوت شغال 100%")

    if text == "رجوع":
        return await start(update, context)

    return await update.message.reply_text("استخدم الأزرار 👇")

# ===================== MAIN (WEBHOOK ONLY) ======================
async def main():
    if not BOT_TOKEN or not APP_URL:
        print("❌ BOT_TOKEN أو APP_URL غير موجودين!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Webhook started...")

    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{APP_URL}/webhook"
    )

if __name__ == "__main__":
    asyncio.run(main())
