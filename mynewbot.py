import os
import logging
from contextlib import asynccontextmanager
from http import HTTPStatus


from fastapi import FastAPI, Request, Response
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Load environment variables (useful for local testing)
load_dotenv() 

# ======================
#   ENVIRONMENT VARS & LOGGING
# ======================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edu-bot")

# ======================
#   HANDLERS (Keep your existing async handlers)
# ======================
# ===== MENUS =====
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
    "رابط ٢": "https://example.com/link2",
}

ALL_SUBJECT_LINKS = {
    "الابتدائية": {"الرياضيات":"...", "اللغة العربية":"...", "العلوم":"...", "اللغة الإنجليزية":"...", "التربية الإسلامية":"...", "الدراسات الاجتماعية":"..."},
    "المتوسطة":   {"الرياضيات":"...", "العلوم":"...", "اللغة الإنجليزية":"...", "اللغة العربية":"...", "الاجتماعيات":"..."},
    "الثانوية":   {"الفيزياء":"...", "الكيمياء":"...", "الأحياء":"...", "الرياضيات":"...", "اللغة العربية":"...", "اللغة الإنجليزية":"...", "الفلسفة":"...", "الإحصاء":"..."},
}

# ✅ زر رجوع داخل القائمة (الخيار A)
SUBJECT_OPTIONS = {
    "main": ["مذكرات", "اختبارات", "فيديوهات", "رجوع"],
    "مذكرات": ["مذكرات نيو", "مذكرات أخرى", "رجوع"],
    "مذكرات نيو": ["المذكرة الشاملة", "ملخصات", "رجوع"],
    "اختبارات": ["قصير أول", "قصير ثاني", "فاينال", "أوراق عمل", "رجوع"],
    "فيديوهات": ["مراجعة", "حل اختبارات", "رجوع"],
}


# ===== Helper keyboard function =====
def kb(rows): return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def show_menu(update: Update, key: str):
    m = MENU_DATA[key]
    await update.message.reply_text(m["text"], reply_markup=kb(m["buttons"]))


# ===== Start command =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["history"] = []      # back stack
    context.user_data["current"] = "main"
    await show_menu(update, "main")


# ===== Main Message Handler =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    cu = context.user_data.get("current", "main")
    hist = context.user_data.setdefault("history", [])

    # 🔙 زر رجوع
    if text == "رجوع":
        if hist:
            prev = hist.pop()
            context.user_data["current"] = prev

            if prev in MENU_DATA:
                return await show_menu(update, prev)

            if prev == "subjects":
                stage = context.user_data.get("stage")
                subs = list(ALL_SUBJECT_LINKS[stage].keys())
                return await update.message.reply_text("📚 اختر المادة:", reply_markup=kb([[s] for s in subs] + [["رجوع"]]))

            if prev == "subject_options":
                return await update.message.reply_text("📂 اختر نوع المحتوى:", reply_markup=kb([[b] for b in SUBJECT_OPTIONS["main"]]))

        context.user_data["current"] = "main"
        return await show_menu(update, "main")

    # روابط مهمة
    if text in IMPORTANT_LINKS:
        return await update.message.reply_text(f"🔗 الرابط:\n{IMPORTANT_LINKS[text]}")

    # الدخول لقائمة مرحلة (ابتدائية/متوسطة/ثانوية)
    if text in MENU_DATA:
        hist.append(cu)
        context.user_data["current"] = text
        return await show_menu(update, text)

    # ✅ إصلاح الفصل الأول / الثاني
    if text in ["الفصل الأول", "الفصل الثاني"]:
        stage = context.user_data.get("current")

        mapping = {
            "الابتدائية": f"{text} (ابتدائي)",
            "المتوسطة": f"{text} (متوسط)",
            "الثانوية": f"{text} (الثانوية)",
        }

        target = mapping.get(stage)

        hist.append(cu)
        context.user_data["current"] = target
        return await show_menu(update, target)

    # اختيار الصف → إظهار مواد الصف
    grades = ["الصف الأول","الصف الثاني","الصف الثالث","الصف الرابع","الصف الخامس",
              "الصف السادس","الصف السابع","الصف الثامن","الصف التاسع",
              "عاشر","حادي عشر أدبي","حادي عشر علمي","ثاني عشر أدبي","ثاني عشر علمي"]

    if text in grades:
        stage = "الابتدائية" if text in grades[:5] else "المتوسطة" if text in grades[5:9] else "الثانوية"
        context.user_data["stage"] = stage
        context.user_data["current"] = "subjects"
        hist.append(cu)

        subs = list(ALL_SUBJECT_LINKS[stage].keys())
        return await update.message.reply_text("📚 اختر المادة:", reply_markup=kb([[s] for s in subs] + [["رجوع"]]))

    # اختيار مادة → عرض (مذكرات / اختبارات / فيديوهات)
    if context.user_data.get("current") == "subjects":
        stage = context.user_data.get("stage")
        if stage and text in ALL_SUBJECT_LINKS[stage]:
            context.user_data["selected_subject"] = text
            context.user_data["current"] = "subject_options"
            hist.append("subjects")

            return await update.message.reply_text("📂 اختر نوع المحتوى:", reply_markup=kb([[b] for b in SUBJECT_OPTIONS["main"]]))

    # اختيار نوع المحتوى (مذكرات/اختبارات/فيديوهات)
    if text in SUBJECT_OPTIONS:
        context.user_data["current"] = text
        hist.append("subject_options")
        return await update.message.reply_text(f"📂 اختر المطلوب ({text}):", reply_markup=kb([[b] for b in SUBJECT_OPTIONS[text]]))

    # روابط داخل القوائم
        # ===== روابط نهائية للمذكرات =====
    if context.user_data.get("current") == "مذكرات نيو":
        if text == "المذكرة الشاملة":
            return await update.message.reply_text("📎 رابط المذكرة الشاملة:\nhttps://example.com/full_note.pdf")

        if text == "ملخصات":
            return await update.message.reply_text("📎 رابط الملخصات:\nhttps://example.com/summary_note.pdf")

    # ===== روابط نهائية للاختبارات =====
    if context.user_data.get("current") == "اختبارات":
        if text == "قصير أول":
            return await update.message.reply_text("📎 رابط قصير أول:\nhttps://example.com/quiz1.pdf")

        if text == "قصير ثاني":
            return await update.message.reply_text("📎 رابط قصير ثاني:\nhttps://example.com/quiz2.pdf")

        if text == "فاينال":
            return await update.message.reply_text("📎 رابط الفاينل:\nhttps://example.com/final.pdf")

        if text == "أوراق عمل":
            return await update.message.reply_text("📎 رابط أوراق العمل:\nhttps://example.com/work.pdf")


    # ===== روابط نهائية للفيديوهات =====
    if context.user_data.get("current") == "فيديوهات":
        if text == "مراجعة":
            return await update.message.reply_text("🎥 فيديوهات مراجعة:\nhttps://example.com/videos-review")

        if text == "حل اختبارات":
            return await update.message.reply_text("🎥 فيديوهات حل الاختبارات:\nhttps://example.com/videos-solutions")

    return await update.message.reply_text("❗ استخدم الأزرار 👇")


# ======================
#   FASTAPI INTEGRATION
# ======================

# Initialize the PTB application builder
ptb_app = (
    Application.builder()
    .token(BOT_TOKEN)
    .updater(None)  # We don't use the built-in updater/webhook runner
    .build()
)

# Add your handlers
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# Define the lifespan manager for FastAPI to start/stop the bot gracefully
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set the webhook URL when the app starts up
    await ptb_app.bot.set_webhook(url=f"{APP_URL}/webhook")
    async with ptb_app:
        yield


# Initialize FastAPI app with the lifespan manager
app = FastAPI(lifespan=lifespan)

# Define the endpoint where Telegram will send updates (must match APP_URL/webhook)
@app.post("/webhook")
async def telegram_webhook(request: Request):
    # Process the update using the PTB application
    update_json = await request.json()
    update = Update.de_json(update_json, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=HTTPStatus.OK)

# This script only defines the FastAPI app; it doesn't run a server itself.
# The 'uvicorn' command on Render runs the server.
