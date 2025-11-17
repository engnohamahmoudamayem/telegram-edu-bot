import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ===== BOT TOKEN =====
BOT_TOKEN = "8297806232:AAHl3aBmcJoV3_AZWqHnangXoHf97rJTJKM"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("edu-bot")

# ===== MENUS =====
def kb(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

MENU_DATA = {
    "main": {
        "text": "منصة تعليمية لطلاب جميع المراحل\n\nمن فضلك اختر المرحلة:",
        "buttons": [["الثانوية", "المتوسطة", "الابتدائية"], ["روابط مهمة"]],
    },

    # المراحل
    "الابتدائية": {"text": "📚 اختر الفصل:", "buttons": [["الفصل الثاني", "الفصل الأول "], ["رجوع"]]},
    "المتوسطة":   {"text": "📚 اختر الفصل:", "buttons": [["الفصل الثاني", "الفصل الأول"], ["رجوع"]]},
    "الثانوية":   {"text": "📚 اختر الفصل:", "buttons": [["الفصل الثاني", "الفصل الأول"], ["رجوع"]]},

    # ابتدائي
    "الفصل الأول (ابتدائي)":  {"text": "📘 اختر الصف:", "buttons": [["الصف الثانى","الصف الأول"],["الصف الرابع","الصف الثالث"],["الصف الخامس"],["رجوع"]]},
    "الفصل الثاني (ابتدائي)": {"text": "📘 اختر الصف:", "buttons": [["الصف الثانى","الصف الأول"],["الصف الرابع","الصف الثالث"],["الصف الخامس"],["رجوع"]]},

    # متوسط
    "الفصل الأول (متوسط)":  {"text": "📘 اختر الصف:", "buttons": [["الصف السابع","الصف السادس"],["الصف التاسع","الصف الثامن"],["رجوع"]]},
    "الفصل الثاني (متوسط)": {"text": "📘 اختر الصف:", "buttons": [["الصف السابع","الصف السادس"],["الصف التاسع","الصف الثامن"],["رجوع"]]},

    # ثانوي
    "الفصل الأول (الثانوية)":  {"text": "📗 اختر الصف/التخصص:", "buttons": [["عاشر"],["حادي عشر أدبي","حادي عشر علمي"],["ثاني عشر أدبي","ثاني عشر علمي"],["رجوع"]]},
    "الفصل الثاني (الثانوية)": {"text": "📗 اختر الصف/التخصص:", "buttons": [["عاشر"],["حادي عشر أدبي","حادي عشر علمي"],["ثاني عشر أدبي","ثاني عشر علمي"],["رجوع"]]},

    "روابط مهمة": {"text": "🔗 اختر الرابط:", "buttons": [["رابط ١","رابط ٢"],["رجوع"]]},
}

IMPORTANT_LINKS = {
    "رابط ١": "https://example.com/link1",
    "رابط 2": "https://example.com/link2",
}

ALL_SUBJECT_LINKS = {
    "الابتدائية": {"الرياضيات":"...", "اللغة العربية":"...", "العلوم":"...", "اللغة الإنجليزية":"...", "التربية الإسلامية":"...", "الدراسات الاجتماعية":"..."},
    "المتوسطة":   {"الرياضيات":"...", "العلوم":"...", "اللغة الإنجليزية":"...", "اللغة العربية":"...", "الاجتماعيات":"..."},
    "الثانوية":   {"الفيزياء":"...", "الكيمياء":"...", "الأحياء":"...", "الرياضيات":"...", "اللغة العربية":"...", "اللغة الإنجليزية":"...", "الفلسفة":"...", "الإحصاء":"..."},
}

SUBJECT_OPTIONS = {
    "main": ["مذكرات", "اختبارات", "فيديوهات", "رجوع"],
    "مذكرات": ["مذكرات نيو", "مذكرات أخرى", "رجوع"],
    "مذكرات نيو": ["المذكرة الشاملة", "ملخصات", "رجوع"],
    "اختبارات": ["قصير أول", "قصير ثاني", "فاينال", "أوراق عمل", "رجوع"],
    "فيديوهات": ["مراجعة", "حل اختبارات", "رجوع"],
}

# ===== Helper =====
async def show_menu(update: Update, key: str):
    m = MENU_DATA[key]
    await update.message.reply_text(m["text"], reply_markup=kb(m["buttons"]))

# ===== Start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["history"] = []
    context.user_data["current"] = "main"
    await show_menu(update, "main")

# ===== Handle Messages =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    cu = context.user_data.get("current", "main")
    hist = context.user_data.setdefault("history", [])

    # رجوع
    if text == "رجوع":
        if hist:
            prev = hist.pop()
            context.user_data["current"] = prev

            if prev in MENU_DATA:
                return await show_menu(update, prev)

        context.user_data["current"] = "main"
        return await show_menu(update, "main")

    # روابط مهمة
    if text in IMPORTANT_LINKS:
        return await update.message.reply_text(f"🔗 الرابط:\n{IMPORTANT_LINKS[text]}")

    # الدخول لقائمة
    if text in MENU_DATA:
        hist.append(cu)
        context.user_data["current"] = text
        return await show_menu(update, text)

    return await update.message.reply_text("❗ استخدم الأزرار 👇")


# ===== RUN BOT =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Bot is running on Render...")
    app.run_polling()


if __name__ == "__main__":
    main()
