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
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from dotenv import load_dotenv

# ============================
#   PATHS
# ============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "education_full.db")
print("📌 DATABASE LOCATION =", DB_PATH)

# ============================
#   ENV VARS
# ============================
load_dotenv()
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")


# ============================
#   SUBJECT OPTIONS (STATIC)
# ============================
SUBJECT_OPTIONS = {
    "مذكرات": ["مذكرات نيو", "مذكرات أخرى", "رجوع"],
    "مذكرات نيو": ["المذكرة الشاملة", "ملخصات", "رجوع"],
    "اختبارات": ["قصير أول", "قصير ثاني", "فاينال", "أوراق عمل", "رجوع"],
    "فيديوهات": ["مراجعة", "حل اختبارات", "رجوع"],
}


# ============================
#   DB SCHEMA
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

    CREATE TABLE IF NOT EXISTS resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        option_name TEXT NOT NULL,
        child_name TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    );
    """)

    conn.commit()
    conn.close()


initialize_db()


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
#   START
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    cursor.execute("SELECT name FROM stages")
    stages = [row[0] for row in cursor.fetchall()]

    await update.message.reply_text(
        "اختر المرحلة:",
        reply_markup=ReplyKeyboardMarkup([stages], resize_keyboard=True),
    )


# ============================
#   BACK BUTTON
# ============================
async def go_back(update, state):
    chat_id = update.effective_chat.id
    step = state["step"]

    # suboption ← option
    if step == "suboption":
        state["step"] = "option"
        options = ["مذكرات", "اختبارات", "فيديوهات"]
        return await update.message.reply_text(
            "اختر نوع المحتوى:",
            reply_markup=ReplyKeyboardMarkup([options, ["رجوع"]], resize_keyboard=True),
        )

    # option ← subject
    if step == "option":
        state["step"] = "subject"
        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
        subjects = [s[0] for s in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر المادة:",
            reply_markup=ReplyKeyboardMarkup([[s] for s in subjects] + [["رجوع"]], resize_keyboard=True),
        )

    # subject ← grade
    if step == "subject":
        state["step"] = "grade"
        cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
        grades = [g[0] for g in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر الصف:",
            reply_markup=ReplyKeyboardMarkup([grades, ["رجوع"]], resize_keyboard=True),
        )

    # grade ← term
    if step == "grade":
        state["step"] = "term"
        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
        terms = [t[0] for t in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر الفصل:",
            reply_markup=ReplyKeyboardMarkup([terms, ["رجوع"]], resize_keyboard=True),
        )

    # term ← stage
    if step == "term":
        state["step"] = "stage"
        cursor.execute("SELECT name FROM stages")
        stages = [s[0] for s in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر المرحلة:",
            reply_markup=ReplyKeyboardMarkup([stages], resize_keyboard=True),
        )

    return await start(update, None)


# ============================
#   HANDLER
# ============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    # BACK BUTTON
    if text == "رجوع":
        return await go_back(update, user_state[chat_id])

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]

    # -----------------------------
    # 1) SELECT STAGE
    # -----------------------------
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (row[0],))
        terms = [t[0] for t in cursor.fetchall()]

        return await update.message.reply_text(
            "اختر الفصل:",
            reply_markup=ReplyKeyboardMarkup([terms, ["رجوع"]], resize_keyboard=True),
        )

    # -----------------------------
    # 2) SELECT TERM
    # -----------------------------
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
            reply_markup=ReplyKeyboardMarkup([grades, ["رجوع"]], resize_keyboard=True),
        )

    # -----------------------------
    # 3) SELECT GRADE
    # -----------------------------
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
            reply_markup=ReplyKeyboardMarkup([[s] for s in subjects] + [["رجوع"]], resize_keyboard=True),
        )

    # -----------------------------
    # 4) SELECT SUBJECT
    # -----------------------------
    if state["step"] == "subject":
        cursor.execute("SELECT id FROM subjects WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["subject_id"] = row[0]
        state["step"] = "option"

        options = list(SUBJECT_OPTIONS.keys())

        return await update.message.reply_text(
            "اختر نوع المحتوى:",
            reply_markup=ReplyKeyboardMarkup([options, ["رجوع"]], resize_keyboard=True),
        )

    # -----------------------------
    # 5) SELECT MAIN OPTION
    # -----------------------------
    if state["step"] == "option":

        if text not in SUBJECT_OPTIONS:
            return await update.message.reply_text("❌ خيار غير موجود")

        state["option_name"] = text
        state["step"] = "suboption"

        children = SUBJECT_OPTIONS[text]

        return await update.message.reply_text(
            "اختر القسم الفرعي:",
            reply_markup=ReplyKeyboardMarkup([children], resize_keyboard=True),
        )

    # -----------------------------
    # 6) SUB OPTION — SHOW RESOURCES
    # -----------------------------
    if state["step"] == "suboption":
        option_name = state["option_name"]
        child_name = text

        cursor.execute("""
            SELECT title, url FROM resources
            WHERE subject_id=? AND option_name=? AND child_name=?
        """, (state["subject_id"], option_name, child_name))

        rows = cursor.fetchall()

        if not rows:
            return await update.message.reply_text("❌ لا يوجد محتوى بعد.")

        msg = "📘 *المحتوى المتاح:*\n\n"
        for title, url in rows:
            msg += f"📌 *{title}*\n🔗 {url}\n\n"

        return await update.message.reply_text(msg, parse_mode="Markdown")


# ============================
#   TELEGRAM APP
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
#   FASTAPI LIFESPAN + WEBHOOK
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
