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
#   DB CONNECTION (Global)
# ================================================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ================================================
#   LOGGING
# ================================================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edu-bot")

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
        current_options = [
            opt[0] if isinstance(opt, tuple) else opt
            for opt in options[i:i+2]
        ]
        rows.append(current_options)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ================================================
#   START HANDLER
# ================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    cursor.execute("SELECT name FROM stages ORDER BY id ASC")
    stages = cursor.fetchall()

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

    if chat_id not in user_state:
        user_state[chat_id] = {"step": "stage"}

    state = user_state[chat_id]

    # =============================
    # زر الرجوع ↩️
    # =============================
    if text == "رجوع ↩️":

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

        # fallback
        state["step"] = "stage"
        cursor.execute("SELECT name FROM stages")
        return await update.message.reply_text("اختر المرحلة:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 1) اختيار المرحلة
    # =============================
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (row[0],))
        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 2) اختيار الفصل
    # =============================
    if state["step"] == "term":
        cursor.execute("SELECT id FROM terms WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["term_id"] = row[0]
        state["step"] = "grade"

        cursor.execute("SELECT name FROM grades WHERE term_id=?", (row[0],))
        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 3) اختيار الصف
    # =============================
    if state["step"] == "grade":
        cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["grade_id"] = row[0]
        state["step"] = "subject"

        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (row[0],))
        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 4) اختيار المادة
    # =============================
    if state["step"] == "subject":
        cursor.execute("SELECT id FROM subjects WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["subject_id"] = row[0]
        state["step"] = "option"

        cursor.execute("""
            SELECT subject_options.name
            FROM subject_option_map
            JOIN subject_options
               ON subject_options.id = subject_option_map.option_id
            WHERE subject_option_map.subject_id=?
        """, (row[0],))
        return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 5) اختيار نوع المحتوى
    # =============================
    if state["step"] == "option":
        cursor.execute("SELECT id FROM subject_options WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
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
        return await update.message.reply_text("اختر القسم الفرعي:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 6) اختيار القسم الفرعي وإظهار المحتوى
    # =============================
    if state["step"] == "suboption":
        cursor.execute("""
            SELECT id FROM option_children
            WHERE name=? AND option_id=?
        """, (text, state["option_id"]))
        row = cursor.fetchone()
        if not row:
            return

        child_id = row[0]

        cursor.execute("""
            SELECT title, url
            FROM resources
            WHERE subject_id=? AND option_id=? AND child_id=?
        """, (state["subject_id"], state["option_id"], child_id))
        data = cursor.fetchall()

        if not data:
            return await update.message.reply_text("لا يوجد محتوى حالياً", reply_markup=make_keyboard([]))

        msg = "إليك المحتوى المتوفر:\n\n"
        for title, url in data:
            msg += f"▪️ <a href='{url}'>{title}</a>\n"

        return await update.message.reply_text(
            msg,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=make_keyboard([])
        )

# ================================================
#   TELEGRAM & FastAPI SETUP
# ================================================
app = FastAPI()
app.state.tg_application = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting bot application & checking DB schema...")

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
    running_app = app.state.tg_application
    if running_app is None:
        return Response(status_code=503)

    update = Update.de_json(await request.json(), running_app.bot)
    await running_app.process_update(update)
    return Response(status_code=200)

@app.get("/")
def read_root():
    return {"status": "Service is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
