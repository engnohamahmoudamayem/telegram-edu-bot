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
MAIN_OPTIONS = ["مذكرات", "اختبارات", "فيديوهات"]  # مذكرات يمين
MEMO_OPTIONS = ["مذكرات نيو", "مذكرات أخرى"]
MEMO_NEW_OPTIONS = ["المذكرة الشاملة", "ملخصات"]
TEST_OPTIONS = ["قصير أول", "قصير ثاني", "فاينال", "أوراق عمل"]
VIDEO_OPTIONS = ["مراجعة", "حل اختبارات"]

# روابط تجريبية
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

    stages = ["الابتدائية", "المتوسطة", "الثانوية"]  # الابتدائية يمين

    await update.message.reply_text(
        "اختر المرحلة:",
        reply_markup=make_keyboard(stages)
    )


# ============================
#   MESSAGE HANDLER
# ============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]

    # ---------------- BACK --------------
    if text == "رجوع ↩️":
        step = state["step"]

        if step == "term":
            state["step"] = "stage"
            stages = ["الابتدائية", "المتوسطة", "الثانوية"]
            return await update.message.reply_text(
                "اختر المرحلة:",
                reply_markup=make_keyboard(stages)
            )

        if step == "grade":
            state["step"] = "term"
            cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
            terms = [t[0] for t in cursor.fetchall()]
            terms = ["الفصل الأول", "الفصل الثاني"]
            return await update.message.reply_text(
                "اختر الفصل:",
                reply_markup=make_keyboard(terms)
            )

        if step == "subject":
            state["step"] = "grade"
            return await handle_grade_return(update, state)

        if step == "main_option":
            state["step"] = "subject"
            cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
            names = [n[0] for n in cursor.fetchall()]
            return await update.message.reply_text(
                "اختر المادة:",
                reply_markup=make_keyboard(names)
            )

        if step in ("memo_kind", "test_kind", "video_kind"):
            state["step"] = "main_option"
            return await update.message.reply_text(
                "اختر نوع المحتوى:",
                reply_markup=make_keyboard(MAIN_OPTIONS)
            )

        if step == "memo_new_kind":
            state["step"] = "memo_kind"
            return await update.message.reply_text(
                "اختر نوع المذكرة:",
                reply_markup=make_keyboard(MEMO_OPTIONS)
            )

        return await start(update, context)

    # ---------------- STAGE --------------
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (row[0],))
        terms = [t[0] for t in cursor.fetchall()]
        terms = ["الفصل الأول", "الفصل الثاني"]

        return await update.message.reply_text(
            "اختر الفصل:",
            reply_markup=make_keyboard(terms)
        )

    # ---------------- TERM --------------
    if state["step"] == "term":
        cursor.execute("SELECT id FROM terms WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["term_id"] = row[0]
        state["step"] = "grade"

        return await handle_grade_return(update, state)

    # ---------------- GRADE --------------
    if state["step"] == "grade":
        cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["grade_id"] = row[0]
        state["step"] = "subject"

        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (row[0],))
        subjects = [s[0] for s in cursor.fetchall()]

        return await update.message.reply_text(
            "اختر المادة:",
            reply_markup=make_keyboard(subjects)
        )

    # ---------------- SUBJECT --------------
    if state["step"] == "subject":
        state["subject_name"] = text
        state["step"] = "main_option"
        return await update.message.reply_text(
            "اختر نوع المحتوى:",
            reply_markup=make_keyboard(MAIN_OPTIONS)
        )

    # ---------------- MAIN OPTION --------------
    if state["step"] == "main_option":

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

    # ---------------- MEMO KIND --------------
    if state["step"] == "memo_kind":

        if text == "مذكرات نيو":
            state["step"] = "memo_new_kind"
            return await update.message.reply_text(
                "اختر الملف:",
                reply_markup=make_keyboard(MEMO_NEW_OPTIONS)
            )

        if text == "مذكرات أخرى":
            url = LINKS_MAP.get("مذكرات أخرى")
            return await update.message.reply_text(f"📌 رابط مذكرات أخرى:\n{url}")

    # ---------------- MEMO NEW KIND --------------
    if state["step"] == "memo_new_kind":
        url = LINKS_MAP.get(text)
        return await update.message.reply_text(f"📌 رابط {text}:\n{url}")

    # ---------------- TEST KIND --------------
    if state["step"] == "test_kind":
        url = LINKS_MAP.get(text)
        return await update.message.reply_text(f"📌 رابط {text}:\n{url}")

    # ---------------- VIDEO KIND --------------
    if state["step"] == "video_kind":
        url = LINKS_MAP.get(text)
        return await update.message.reply_text(f"📌 رابط {text}:\n{url}")


# ============================
#   GRADE RETURN HANDLER
# ============================
async def handle_grade_return(update, state):
    stage_id = state["stage_id"]

    # ابتدائي
    if stage_id == 1:
        ordered = [
            ["الصف الأول", "الصف الثاني"],
            ["الصف الثالث", "الصف الرابع"],
            ["الصف الخامس"],
            ["رجوع ↩️"]
        ]
        return await update.message.reply_text(
            "اختر الصف:",
            reply_markup=ReplyKeyboardMarkup(ordered, resize_keyboard=True)
        )

    # متوسط
    if stage_id == 2:
        ordered = [
            ["الصف السادس", "الصف السابع"],
            ["الصف الثامن", "الصف التاسع"],
            ["رجوع ↩️"]
        ]
        return await update.message.reply_text(
            "اختر الصف:",
            reply_markup=ReplyKeyboardMarkup(ordered, resize_keyboard=True)
        )

    # ثانوي
    if stage_id == 3:
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
