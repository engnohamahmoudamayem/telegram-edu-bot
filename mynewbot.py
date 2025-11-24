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
#   CONFIG
# ============================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
DB_PATH = "education_full.db"

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")

# ============================
#   DB INIT
# ============================
def initialize_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS stages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS terms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        FOREIGN KEY(stage_id) REFERENCES stages(id)
    );

    CREATE TABLE IF NOT EXISTS grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        FOREIGN KEY(term_id) REFERENCES terms(id)
    );

    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grade_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        FOREIGN KEY(grade_id) REFERENCES grades(id)
    );

    CREATE TABLE IF NOT EXISTS subject_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS option_children (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        option_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        FOREIGN KEY(option_id) REFERENCES subject_options(id)
    );

    CREATE TABLE IF NOT EXISTS subject_option_map (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        option_id INTEGER NOT NULL,
        FOREIGN KEY(subject_id) REFERENCES subjects(id),
        FOREIGN KEY(option_id) REFERENCES subject_options(id)
    );

    CREATE TABLE IF NOT EXISTS subject_option_children_map (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        child_id INTEGER NOT NULL,
        FOREIGN KEY(subject_id) REFERENCES subjects(id),
        FOREIGN KEY(child_id) REFERENCES option_children(id)
    );

    CREATE TABLE IF NOT EXISTS resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        option_id INTEGER NOT NULL,
        child_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        url TEXT NOT NULL
    );
    """)

    conn.commit()
    conn.close()

initialize_db()

# ============================
#   LOGGING
# ============================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mynewbot")

# ============================
#   DATABASE
# ============================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ============================
#   USER STATE
# ============================
user_state = {}

# ============================
#   HELPER – Arrange RTL buttons
# ============================
def make_keyboard(items):
    rows = []
    for item in items:
        rows.append([item])
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ============================
#   START
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    cursor.execute("SELECT name FROM stages")
    stages = [s[0] for s in cursor.fetchall()]

    # make ابتدائية first (right)
    if "الابتدائية" in stages:
        stages.remove("الابتدائية")
        stages.insert(0, "الابتدائية")

    await update.message.reply_text(
        "اختر المرحلة:",
        reply_markup=ReplyKeyboardMarkup([stages, ["رجوع ↩️"]], resize_keyboard=True),
    )

# ============================
#   MESSAGE HANDLER
# ============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    if text == "رجوع ↩️":
        return await start(update, context)

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]

    # =============================
    # STAGE
    # =============================
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return
        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (row[0],))
        terms = [t[0] for t in cursor.fetchall()]

        # الفصل الأول على اليمين
        if "الفصل الأول" in terms:
            terms.remove("الفصل الأول")
            terms.insert(0, "الفصل الأول")

        return await update.message.reply_text(
            "اختر الفصل:",
            reply_markup=ReplyKeyboardMarkup([terms, ["رجوع ↩️"]], resize_keyboard=True),
        )

    # =============================
    # TERM
    # =============================
    if state["step"] == "term":
        cursor.execute("SELECT id FROM terms WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return
        state["term_id"] = row[0]
        state["step"] = "grade"

        cursor.execute("SELECT name FROM grades WHERE term_id=?", (row[0],))
        grades = [g[0] for g in cursor.fetchall()]

        return await update.message.reply_text(
            "اختر الصف:",
            reply_markup=ReplyKeyboardMarkup([grades, ["رجوع ↩️"]], resize_keyboard=True),
        )

    # =============================
    # GRADE
    # =============================
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
            reply_markup=make_keyboard(subjects),
        )

    # =============================
    # SUBJECT → OPTIONS
    # =============================
    if state["step"] == "subject":
        cursor.execute("SELECT id FROM subjects WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return
        state["subject_id"] = row[0]
        state["step"] = "option"

        options = ["مذكرات", "اختبارات", "فيديوهات"]
        return await update.message.reply_text(
            "اختر نوع المحتوى:",
            reply_markup=make_keyboard(options),
        )

    # =============================
    # OPTION → SUB OPTIONS
    # =============================
    if state["step"] == "option":
        state["option_selected"] = text

        if text == "مذكرات":
            return await update.message.reply_text(
                "اختر نوع المذكرة:",
                reply_markup=make_keyboard(["مذكرات نيو", "مذكرات أخرى"]),
            )

        elif text == "اختبارات":
            return await update.message.reply_text(
                "اختر نوع الاختبار:",
                reply_markup=make_keyboard(["قصير أول", "قصير ثاني", "فاينال", "أوراق عمل"]),
            )

        elif text == "فيديوهات":
            return await update.message.reply_text(
                "اختر نوع الفيديو:",
                reply_markup=make_keyboard(["مراجعة", "حل اختبارات"]),
            )

    # =============================
    # SUBOPTION → LINKS
    # =============================
    if state["step"] == "option" or state["step"] == "subject" or state["step"] == "grade":
        return

    # مذكرات نيو → المذكرة الشاملة + ملخصات
    if text == "مذكرات نيو":
        state["step"] = "suboption"
        return await update.message.reply_text(
            "اختر نوع الملف:",
            reply_markup=make_keyboard(["المذكرة الشاملة", "ملخصات"]),
        )

    # الروابط الوهمية
    fake_links = {
        "المذكرة الشاملة": "https://example.com/shamela",
        "ملخصات": "https://example.com/summary",
        "قصير أول": "https://example.com/q1",
        "قصير ثاني": "https://example.com/q2",
        "فاينال": "https://example.com/final",
        "أوراق عمل": "https://example.com/work",
        "مراجعة": "https://example.com/review",
        "حل اختبارات": "https://example.com/solve",
        "مذكرات أخرى": "https://example.com/other",
    }

    if text in fake_links:
        return await update.message.reply_text(
            f"📌 الرابط:\n{fake_links[text]}"
        )

# ============================
#   TELEGRAM BOT
# ============================
ptb_app = (
    Application.builder()
    .token(BOT_TOKEN)
    .updater(None)
    .build()
)

ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ============================
#   FASTAPI + WEBHOOK
# ============================
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
