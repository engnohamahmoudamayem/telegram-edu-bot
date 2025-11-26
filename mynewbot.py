# ================================================
#   IMPORTS & PATHS
# ================================================
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

# Load env
load_dotenv()

# === FIXED DB LOCATION ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "edu_bot_data.db")
print("📌 DATABASE LOCATION =", DB_PATH)

# ================================================
#   ENVIRONMENT VARIABLES
# ================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")

# ================================================
#   DB CONNECTION
# ================================================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ================================================
#   LOGGING
# ================================================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("DEBUG-BOT")

# ================================================
#   USER STATE MEMORY
# ================================================
user_state = {}

# ============================
#   GENERIC KEYBOARD MAKER
# ============================
def make_keyboard(options):
    rows = []
    for i in range(0, len(options), 2):
        current = [
            opt[0] if isinstance(opt, tuple) else opt
            for opt in options[i:i+2]
        ]
        rows.append(current)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ================================================
#   START HANDLER
# ================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log.info("🔥🔥 START HANDLER CALLED 🔥🔥")

    user_state[chat_id] = {"step": "stage"}

    cursor.execute("SELECT name FROM stages ORDER BY id ASC")
    stages = cursor.fetchall()
    log.info(f"🔍 STAGES = {stages}")

    await update.message.reply_text(
        "اختر المرحلة:",
        reply_markup=make_keyboard(stages)
    )

# ================================================
#   MESSAGE HANDLER
# ================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    log.info(f"📩 USER CLICKED: '{text}'")

    if chat_id not in user_state:
        log.warning("⚠️ USER HAS NO STATE → restarting start()")
        return await start(update, context)

    state = user_state[chat_id]

    # --------------------------------------------
    # رجوع
    # --------------------------------------------
    if text == "رجوع ↩️":
        log.info(f"🔙 BACK BUTTON PRESSED | Current step = {state['step']}")

        if state["step"] == "term":
            state["step"] = "stage"
            cursor.execute("SELECT name FROM stages")
            return await update.message.reply_text("اختر المرحلة:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "grade":
            state["step"] = "term"
            cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
            return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "subject":
            state["step"] = "grade"
            cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
            return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "option":
            state["step"] = "subject"
            cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
            return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "suboption":
            state["step"] = "option"
            cursor.execute("""
                SELECT subject_options.name
                FROM subject_option_map
                JOIN subject_options
                    ON subject_options.id = subject_option_map.option_id
                WHERE subject_option_map.subject_id=?
            """, (state["subject_id"],))
            return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(cursor.fetchall()))

        return await start(update, context)

    # --------------------------------------------
    # اختيار المرحلة
    # --------------------------------------------
    if state["step"] == "stage":
        log.info(f"📌 STAGE CLICKED = '{text}'")

        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        log.info(f"🎯 STAGE MATCH RESULT = {row}")

        if not row:
            log.warning("❌ Stage not found!")
            return

        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
        terms = cursor.fetchall()
        log.info(f"📚 TERMS = {terms}")

        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(terms))

    # --------------------------------------------
    # اختيار الفصل
    # --------------------------------------------
    if state["step"] == "term":
        log.info(f"📌 TERM CLICKED = '{text}'")

        cursor.execute("SELECT id FROM terms WHERE name=?", (text,))
        row = cursor.fetchone()
        log.info(f"🎯 TERM MATCH RESULT = {row}")

        if not row:
            log.warning("❌ Term not found!")
            return

        state["term_id"] = row[0]
        state["step"] = "grade"

        cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
        grades = cursor.fetchall()
        log.info(f"📚 GRADES = {grades}")

        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(grades))

    # --------------------------------------------
    # اختيار الصف
    # --------------------------------------------
    if state["step"] == "grade":
        log.info(f"📌 GRADE CLICKED = '{text}'")

        cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
        row = cursor.fetchone()
        log.info(f"🎯 GRADE MATCH RESULT = {row}")

        if not row:
            log.warning("❌ Grade not found!")
            return

        state["grade_id"] = row[0]
        state["step"] = "subject"

        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
        subjects = cursor.fetchall()
        log.info(f"📚 SUBJECTS = {subjects}")

        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(subjects))

    # --------------------------------------------
    # اختيار المادة
    # --------------------------------------------
    if state["step"] == "subject":
        log.info(f"📌 SUBJECT CLICKED = '{text}'")

        cursor.execute("SELECT id FROM subjects WHERE name=?", (text,))
        row = cursor.fetchone()
        log.info(f"🎯 SUBJECT MATCH RESULT = {row}")

        if not row:
            log.warning("❌ Subject not found!")
            return

        state["subject_id"] = row[0]
        state["step"] = "option"

        cursor.execute("""
            SELECT subject_options.name
            FROM subject_option_map
            JOIN subject_options
                ON subject_options.id = subject_option_map.option_id
            WHERE subject_option_map.subject_id=?
        """, (state["subject_id"],))

        options = cursor.fetchall()
        log.info(f"📚 OPTIONS = {options}")

        return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(options))

    # --------------------------------------------
    # اختيار النوع مذكرات / اختبارات
    # --------------------------------------------
    if state["step"] == "option":
        log.info(f"📌 OPTION CLICKED = '{text}'")

        cursor.execute("SELECT id FROM subject_options WHERE name=?", (text,))
        row = cursor.fetchone()
        log.info(f"🎯 OPTION MATCH RESULT = {row}")

        if not row:
            log.warning("❌ Option not found!")
            return

        state["option_id"] = row[0]
        state["step"] = "suboption"

        cursor.execute("""
            SELECT option_children.name
            FROM subject_option_children_map
            JOIN option_children
               ON option_children.id = subject_option_children_map.child_id
            WHERE subject_option_children_map.subject_id=?
              AND option_children.option_id=?
        """, (state["subject_id"], state["option_id"]))

        children = cursor.fetchall()
        log.info(f"📚 SUBOPTIONS = {children}")

        return await update.message.reply_text("اختر القسم الفرعي:", reply_markup=make_keyboard(children))

    # --------------------------------------------
    # اختيار القسم الفرعي النهائي
    # --------------------------------------------
    if state["step"] == "suboption":
        log.info(f"📌 SUBOPTION CLICKED = '{text}'")

        cursor.execute("""
            SELECT id FROM option_children
            WHERE name=? AND option_id=?
        """, (text, state["option_id"]))

        row = cursor.fetchone()
        log.info(f"🎯 SUBOPTION MATCH RESULT = {row}")

        if not row:
            log.warning("❌ Suboption not found!")
            return

        child_id = row[0]

        cursor.execute("""
            SELECT title, url
            FROM resources
            WHERE subject_id=? AND option_id=? AND child_id=?
        """, (state["subject_id"], state["option_id"], child_id))

        resources = cursor.fetchall()
        log.info(f"📚 RESOURCES FOUND = {resources}")

        if not resources:
            return await update.message.reply_text("لا يوجد محتوى حالياً.", reply_markup=make_keyboard([]))

        text_msg = "إليك المحتوى:\n\n"
        for title, url in resources:
            text_msg += f"▪️ <a href='{url}'>{title}</a>\n"

        return await update.message.reply_text(
            text_msg,
            parse_mode="HTML",
            reply_markup=make_keyboard([]),
            disable_web_page_preview=True
        )

# ================================================
#   TELEGRAM + FASTAPI
# ================================================
app = FastAPI()
app.state.tg_application = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 LIFESPAN START")
    log.info(f"📌 DATABASE FILE = {DB_PATH}")
    log.info(f"🌍 APP_URL   = {APP_URL}")
    log.info(f"🚀 BOT_TOKEN = {BOT_TOKEN}")

    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.state.tg_application = tg_app

    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")

    async with tg_app:
        await tg_app.start()
        yield
        await tg_app.stop()

app.router.lifespan_context = lifespan

@app.post("/telegram")
async def telegram_webhook(request: Request):
    update = Update.de_json(await request.json(), app.state.tg_application.bot)
    await app.state.tg_application.process_update(update)
    return Response(status_code=200)

@app.get("/")
def root():
    return {"status": "running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
