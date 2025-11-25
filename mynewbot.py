# ============================
#   IMPORTS
# ============================
import os
import sqlite3
import logging
from http import HTTPStatus
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from dotenv import load_dotenv
load_dotenv()

# ============================
#   ENVIRONMENT
# ============================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
DB_PATH = "education_full.db"

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")

# ============================
#   LOGGING
# ============================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edu-bot")

# ============================
#   DB CONNECTION
# ============================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ============================
#   USER STATE
# ============================
user_state = {}

# ============================
#   STATIC OPTIONS
# ============================
MAIN_OPTIONS = ["مذكرات", "اختبارات", "فيديوهات"]
MEMO_OPTIONS = ["مذكرات نيو", "مذكرات أخرى"]
MEMO_NEW_OPTIONS = ["المذكرة الشاملة", "ملخصات"]
TEST_OPTIONS = ["قصير أول", "قصير ثاني", "فاينال", "أوراق عمل"]
VIDEO_OPTIONS = ["مراجعة", "حل اختبارات"]

LINKS_MAP = {
    "المذكرة الشاملة": "https://example.com/shamela",
    "ملخصات": "https://example.com/summary",
    "مذكرات أخرى": "https://example.com/other-notes",

    "قصير أول": "https://example.com/q1",
    "قصير ثاني": "https://example.com/q2",
    "فاينال": "https://example.com/final",
    "أوراق عمل": "https://example.com/sheets",

    "مراجعة": "https://example.com/revision",
    "حل اختبارات": "https://example.com/exams",
}

# ============================
#   KEYBOARD MAKER
# ============================
def make_keyboard(options):
    rows = []
    row = []

    for opt in options:
        row.append(opt)
        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ============================
#   /start
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    stages = ["الابتدائية", "المتوسطة", "الثانوية"]

    await update.message.reply_text(
        "اختر المرحلة:",
        reply_markup=make_keyboard(stages)
    )

# ============================
#   BACK HANDLER
# ============================
async def handle_back(update, context, state):

    # من خطوة الفصل ← رجوع للمرحلة
    if state["step"] == "term":
        state["step"] = "stage"
        return await update.message.reply_text(
            "اختر المرحلة:",
            reply_markup=make_keyboard(["الابتدائية", "المتوسطة", "الثانوية"])
        )

    # من الصف ← رجوع للفصل
    if state["step"] == "grade":
        state["step"] = "term"
        terms = ["الفصل الأول", "الفصل الثاني"]
        return await update.message.reply_text(
            "اختر الفصل:",
            reply_markup=make_keyboard(terms)
        )

    # من المواد ← رجوع للصفوف
    if state["step"] == "subject":
        state["step"] = "grade"
        return await handle_grade_return(update, state)

    # من نوع المحتوى ← رجوع للمواد
    if state["step"] == "main_option":
        state["step"] = "subject"
        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
        names = [n[0] for n in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر المادة:",
            reply_markup=make_keyboard(names)
        )

    # من داخل (مذكرات-اختبارات-فيديو) رجوع للثلاث خيارات
    if state["step"] in ("memo_kind", "test_kind", "video_kind"):
        state["step"] = "main_option"
        return await update.message.reply_text(
            "اختر نوع المحتوى:",
            reply_markup=make_keyboard(MAIN_OPTIONS)
        )

    # من مذكرات نيو ← رجوع لأنواع المذكرات
    if state["step"] == "memo_new_kind":
        state["step"] = "memo_kind"
        return await update.message.reply_text(
            "اختر نوع المذكرة:",
            reply_markup=make_keyboard(MEMO_OPTIONS)
        )

    return await start(update, context)

# ============================
#   STEP HANDLERS
# ============================

async def handle_stage(update, context, text, state):
    cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
    row = cursor.fetchone()
    if not row:
        return

    state["stage_id"] = row[0]
    state["step"] = "term"

    await update.message.reply_text(
        "اختر الفصل:",
        reply_markup=make_keyboard(["الفصل الأول", "الفصل الثاني"])
    )


async def handle_term(update, context, text, state):
    cursor.execute("SELECT id FROM terms WHERE name=?", (text,))
    row = cursor.fetchone()
    if not row:
        return

    state["term_id"] = row[0]
    state["step"] = "grade"

    await handle_grade_return(update, state)


async def handle_grade(update, context, text, state):
    cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
    row = cursor.fetchone()
    if not row:
        return

    state["grade_id"] = row[0]
    state["step"] = "subject"

    cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (row[0],))
    subjects = [s[0] for s in cursor.fetchall()]

    await update.message.reply_text(
        "اختر المادة:",
        reply_markup=make_keyboard(subjects)
    )


async def handle_subject(update, context, text, state):
    state["subject_name"] = text
    state["step"] = "main_option"

    await update.message.reply_text(
        "اختر نوع المحتوى:",
        reply_markup=make_keyboard(MAIN_OPTIONS)
    )


async def handle_main_option(update, context, text, state):

    if text == "مذكرات":
        state["step"] = "memo_kind"
        return await update.message.reply_text(
            "اختر نوع المذكرات:",
            reply_markup=make_keyboard(MEMO_OPTIONS)
        )

    if text == "اختبارات":
        state["step"] = "test_kind"
        return await update.message.reply_text(
            "اختر نوع الاختبار:",
            reply_markup=make_keyboard(TEST_OPTIONS)
        )

    if text == "فيديوهات":
        state["step"] = "video_kind"
        return await update.message.reply_text(
            "اختر نوع الفيديو:",
            reply_markup=make_keyboard(VIDEO_OPTIONS)
        )


async def handle_memo_kind(update, context, text, state):

    if text == "مذكرات نيو":
        state["step"] = "memo_new_kind"
        return await update.message.reply_text(
            "اختر الملف:",
            reply_markup=make_keyboard(MEMO_NEW_OPTIONS)
        )

    if text == "مذكرات أخرى":
        return await update.message.reply_text(f"📌 الرابط:\n{LINKS_MAP['مذكرات أخرى']}")


async def handle_memo_new(update, context, text, state):
    return await update.message.reply_text(f"📌 الرابط:\n{LINKS_MAP[text]}")


async def handle_test_kind(update, context, text, state):
    return await update.message.reply_text(f"📌 الرابط:\n{LINKS_MAP[text]}")


async def handle_video_kind(update, context, text, state):
    return await update.message.reply_text(f"📌 الرابط:\n{LINKS_MAP[text]}")

# ============================
#   ROUTER TABLE
# ============================
STEP_ROUTER = {
    "stage": handle_stage,
    "term": handle_term,
    "grade": handle_grade,
    "subject": handle_subject,
    "main_option": handle_main_option,
    "memo_kind": handle_memo_kind,
    "memo_new_kind": handle_memo_new,
    "test_kind": handle_test_kind,
    "video_kind": handle_video_kind,
}

# ============================
#   GRADE RETURN HANDLER
# ============================
async def handle_grade_return(update, state):

    stage_id = state["stage_id"]

    if stage_id == 1:  # ابتدائي
        ordered = [
            ["الصف الأول", "الصف الثاني"],
            ["الصف الثالث", "الصف الرابع"],
            ["الصف الخامس"],
            ["رجوع ↩️"]
        ]

    elif stage_id == 2:  # المتوسط
        ordered = [
            ["الصف السادس", "الصف السابع"],
            ["الصف الثامن", "الصف التاسع"],
            ["رجوع ↩️"]
        ]

    else:  # ثانوي
        ordered = [
            ["عاشر"],
            ["حادي عشر أدبي", "حادي عشر علمي"],
            ["ثاني عشر أدبي", "ثاني عشر علمي"],
            ["رجوع ↩️"]
        ]

    return await update.message.reply_text(
        "اختر الصف:",
        reply_markup=ReplyKeyboardMarkup(ordered, resize_keyboard=True)
    )

# ============================
#   MAIN MESSAGE HANDLER
# ============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]

    # زر الرجوع
    if text == "رجوع ↩️":
        return await handle_back(update, context, state)

    # تشغيل دالة الخطوة الحالية
    step = state["step"]

    if step in STEP_ROUTER:
        return await STEP_ROUTER[step](update, context, text, state)

    else:
        return await update.message.reply_text("❌ حدث خطأ غير متوقع في الخطوة.")

# ============================
#   TELEGRAM / FASTAPI
# ============================
ptb_app = (
    Application.builder()
    .token(BOT_TOKEN)
    .updater(None)
    .build()
)

ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ptb_app.bot.set_webhook(f"{APP_URL}/webhook")
    async with ptb_app:
        yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    update_json = await request.json()
    update = Update.de_json(update_json, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=HTTPStatus.OK)
