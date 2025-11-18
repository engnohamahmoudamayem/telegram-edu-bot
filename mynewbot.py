import os
import logging
from telegram import Update, ReplyKeyboardMarkup # Added ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import asyncio # Added asyncio import

# ======================
#   ENVIRONMENT VARS & LOGGING
# ======================
# These variables rely on your Render environment settings
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
PORT = int(os.environ.get("PORT", "10000"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edu-bot")

# ======================
#   KEYBOARD HELPER
# ======================
def kb(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ======================
#   HANDLERS
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "البوت اشتغل بنجاح ✔️",
        reply_markup=kb([["اختبار", "رجوع"]])
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "اختبار":
        return await update.message.reply_text("شغال 100% يا باشمهندسة ✔️")

    if text == "رجوع":
        return await start(update, context)

    await update.message.reply_text("استخدمي الأزرار 👇")

# ======================
#   MAIN APPLICATION LOGIC (WEBHOOK MODE for Render)
# ======================

async def main():
    # Check if environment variables are set
    if not BOT_TOKEN or not APP_URL:
        log.error("❌ BOT_TOKEN أو APP_URL غير موجودين في إعدادات Render!")
        # Raising an exception makes Render stop the deploy process with an error message
        raise RuntimeError("Missing Environment Variables")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Set up the webhook configuration required by Render
    log.info(f"🚀 Webhook running on port {PORT} with URL {APP_URL}/webhook")
    
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{APP_URL}/webhook",
    )


# The platform (like Render) will call this function to start the web service.
if __name__ == "__main__":
    # In a production environment like Render, we call main() directly.
    # The platform handles the asyncio event loop and keeps the process running.
    main() 

