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
#   ENVIRONMENT VARIABLES
# ============================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")  # example: https://your-app.onrender.com
DB_PATH = "education_full.db"

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing in environment variables!")

# ============================
#   LOGGING
# ============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("edu-bot")

# ============================
#   DATABASE CONNECTION
# ============================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ============================
#   USER STATE MEMORY
# ============================
user_state = {}

# ============================
#   /START HANDLER
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
#   MESSAGE HANDLER
# ============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    # ================================================
    #   BACK BUTTON LOGIC
    # ================================================
    if text == "رجوع ↩️":
        state = user_state.get(chat_id, {})
        step = state.get("step", "")

        # suboption → option
        if step == "suboption":
            state["step"] = "option"
            cursor.execute("""
                SELECT subject_options.name
                FROM subject_option_map
                JOIN subject_options ON subject_options.id = subject_option_map.option_id
                WHERE subject_option_map.subject_id=?
            """, (state["subject_id"],))
            options = [o[0] for o in cursor.fetchall()]
            return await update.message.reply_text(
                "اختر نوع المحتوى:",
                reply_markup=ReplyKeyboardMarkup([options, ["رجوع ↩️"]], resize_keyboard=True),
            )

        # option → subject
        if step == "option":
            state["step"] = "subject"
            cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
            subjects = [s[0] for s in cursor.fetchall()]
            return await update.message.reply_text(
                "اختر المادة:",
                reply_markup=ReplyKeyboardMarkup([[s] for s in subjects] + [["رجوع ↩️"]], resize_keyboard=True),
            )

        # subject → grade
        if step == "subject":
            state["step"] = "grade"
            cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
            grades = [g[0] for g in cursor.fetchall()]
            return await update.message.reply_text(
                "اختر الصف:",
                reply_markup=ReplyKeyboardMarkup([grades, ["رجوع ↩️"]], resize_keyboard=True),
            )

        # grade → term
        if step == "grade":
            state["step"] = "term"
            cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
            terms = [t[0] for t in cursor.fetchall()]
            return await update.message.reply_text(
                "اختر الفصل:",
                reply_markup=ReplyKeyboardMarkup([terms, ["رجوع ↩️"]], resize_keyboard=True),
            )

        # term → stage
        if step == "term":
            state["step"] = "stage"
            cursor.execute("SELECT name FROM stages")
            stages = [s[0] for s in cursor.fetchall()]
            return await update.message.reply_text(
                "اختر المرحلة:",
                reply_markup=ReplyKeyboardMarkup([stages], resize_keyboard=True),
            )

        return await start(update, context)

    # ==================================================
    #   IF STATE RESET
    # ==================================================
    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]

    # --------------------------------------------------
    #   1) SELECT STAGE
    # --------------------------------------------------
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (row[0],))
        terms = [t[0] for t in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر الفصل:",
            reply_markup=ReplyKeyboardMarkup([terms, ["رجوع ↩️"]], resize_keyboard=True),
        )

    # --------------------------------------------------
    #   2) SELECT TERM
    # --------------------------------------------------
    if state["step"] == "term":
        cursor.execute("SELECT id FROM terms WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["term_id"] = row[0]
        state["step"] = "grade"

        cursor.execute("SELECT name FROM grades WHERE term_id=?", (row[0],))
        grades = [g[0] for g in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر الصف:",
            reply_markup=ReplyKeyboardMarkup([grades, ["رجوع ↩️"]], resize_keyboard=True),
        )

    # --------------------------------------------------
    #   3) SELECT GRADE
    # --------------------------------------------------
    if state["step"] == "grade":
        cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["grade_id"] = row[0]
        state["step"] = "subject"

        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (row[0],))
        subjects = [s[0] for s in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر المادة:",
            reply_markup=ReplyKeyboardMarkup([[s] for s in subjects] + [["رجوع ↩️"]], resize_keyboard=True),
        )

    # --------------------------------------------------
    #   4) SELECT SUBJECT
    # --------------------------------------------------
    if state["step"] == "subject":
        cursor.execute("SELECT id FROM subjects WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["subject_id"] = row[0]
        state["step"] = "option"

        cursor.execute("""
            SELECT subject_options.name
            FROM subject_option_map
            JOIN subject_options ON subject_options.id = subject_option_map.option_id
            WHERE subject_option_map.subject_id=?
        """, (row[0],))
        options = [o[0] for o in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر نوع المحتوى:",
            reply_markup=ReplyKeyboardMarkup([options, ["رجوع ↩️"]], resize_keyboard=True),
        )

    # --------------------------------------------------
    #   5) SELECT MAIN OPTION (اختبارات/مذكرات/فيديوهات)
    # --------------------------------------------------
    if state["step"] == "option":
        cursor.execute("SELECT id FROM subject_options WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["option_id"] = row[0]
        state["step"] = "suboption"

        cursor.execute("""
            SELECT option_children.name
            FROM subject_option_children_map
            JOIN option_children ON option_children.id = subject_option_children_map.child_id
            WHERE subject_option_children_map.subject_id=?
        """, (state["subject_id"],))
        children = [c[0] for c in cursor.fetchall()]
        return await update.message.reply_text(
            "اختر القسم الفرعي:",
            reply_markup=ReplyKeyboardMarkup([children, ["رجوع ↩️"]], resize_keyboard=True),
        )

    # --------------------------------------------------
    #   6) SUB OPTION — SHOW RESOURCES
    # --------------------------------------------------
    if state["step"] == "suboption":

        # 1) get child_id
        cursor.execute("SELECT id FROM option_children WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return await update.message.reply_text("❌ لا يوجد هذا المحتوى!")
        child_id = row[0]

        subject_id = state["subject_id"]
        option_id = state["option_id"]

        # 2) fetch resources
        cursor.execute("""
            SELECT title, url
            FROM resources
            WHERE subject_id = ?
              AND option_id = ?
              AND child_id = ?
        """, (subject_id, option_id, child_id))

        resources = cursor.fetchall()

        # 3) no content
        if not resources:
            return await update.message.reply_text(
                "❌ لا يوجد محتوى لهذا القسم.\n🔄 سيتم إضافته قريبًا."
            )

        # 4) show content
        msg = "📘 *المحتوى المتاح:*\n\n"
        for title, url in resources:
            msg += f"📌 *{title}*\n🔗 {url}\n\n"

        return await update.message.reply_text(msg, parse_mode="Markdown")


# ============================
#   TELEGRAM APPLICATION
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
#   FASTAPI LIFESPAN
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