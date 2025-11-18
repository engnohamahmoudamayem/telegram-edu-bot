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

<<<<<<< HEAD
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

=====
def main():
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN is not set in environment variables!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

   BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")    # https://your-app.onrender.com
PORT = int(os.environ.get("PORT", "10000"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edu-bot")


def kb(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


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



async def main():
    if not BOT_TOKEN or not APP_URL:
        print("❌ BOT_TOKEN أو APP_URL غير موجودين")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()


    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    print("✅ Bot is running with polling...")

    app.run_polling()

    print("🚀 Webhook running...")

    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{APP_URL}/webhook",
    )



if __name__ == "__main__":
    main()
