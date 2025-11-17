import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== الإعدادات ==================
# هنجِيب التوكن من Environment Variable على Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("edu-bot")


# ================== الأوامر ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً! البوت شغال من Render.\n\n"
        "جرّب تبعتلي أي رسالة وأنا هكررها لك 😉"
    )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # يكرر نفس الكلام اللى المستخدم كتبه
    await update.message.reply_text(update.message.text)


# ================== MAIN (Polling عادي) ==================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN is not set in environment variables!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("✅ Bot is running with polling...")
    # run_polling بلوكينج، ومش محتاجة asyncio.run
    app.run_polling()


if __name__ == "__main__":
    main()
