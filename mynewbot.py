import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
import asyncio

# ======================
#   ENVIRONMENT VARS
# ======================
BOT_TOKEN = os.environ.get("8297806232:AAHl3aBmcJoV3_AZWqHnangXoHf97rJTJKM")
APP_URL = os.environ.get("APP_URL")  # https://your-app.onrender.com
PORT = int(os.environ.get("PORT", 10000))

# ======================
#   LOGGING
# ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("edu-bot")

# ======================
#   KEYBOARD HELPER
# ======================
def kb(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ======================
#   MENUS
# ======================
MENU_DATA = {
    "main": {
        "text": "منصة تعليمية لطلاب جميع المراحل\n\nمن فضلك اختر المرحلة:",
        "buttons": [["الثانوية", "المتوسطة", "الابتدائية"], ["روابط مهمة"]],
    },

    "الابتدائية": {"text": "📚 اختر الفصل:", "buttons": [["الفصل الثاني", "الفصل الأول"], ["رجوع"]]},
    "المتوسطة":   {"text": "📚 اختر الفصل:", "buttons": [["الفصل الثاني", "الفصل الأول"], ["رجوع"]]},
    "الثانوية":   {"text": "📚 اختر الفصل:", "buttons": [["الفصل الثاني", "الفصل الأول"], ["رجوع"]]},
}

IMPORTANT_LINKS = {
    "رابط ١": "https://example.com/link1",
    "رابط ٢": "https://example.com/link2",
}

# ======================
#   START COMMAND
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["current"] = "main"
    m = MENU_DATA["main"]
    await update.message.reply_text(m["text"], reply_markup=kb(m["buttons"]))

# ======================
#   MESSAGE HANDLER
# ======================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    cu = context.user_data.get("current", "main")

    # ===== زر رجوع =====
    if text == "رجوع":
        context.user_data["current"] = "main"
        m = MENU_DATA["main"]
        return await update.message.reply_text(m["text"], reply_markup=kb(m["buttons"]))

    # ===== روابط مهمة =====
    if text in IMPORTANT_LINKS:
        return await update.message.reply_text(f"🔗 الرابط:\n{IMPORTANT_LINKS[text]}")

    # ===== الدخول لقوائم MENU_DATA =====
    if text in MENU_DATA:
        context.user_data["current"] = text
        m = MENU_DATA[text]
        return await update.message.reply_text(m["text"], reply_markup=kb(m["buttons"]))

    return await update.message.reply_text("❗ استخدم الأزرار 👇")


# ======================
#   WEBHOOK MODE
# ======================
# ======================
#   POLLING MODE (التشغيل المحلي)
# ======================
async def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN environment variable not set!")
        print("الرجاء تعيين متغير البيئة BOT_TOKEN !")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # تشغيل البوت في وضع الاستقصاء
    print("Bot is starting in Polling Mode...")
    await app.run_polling(poll_interval=3.0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

