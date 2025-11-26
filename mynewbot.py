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
        current_options = [opt[0] if isinstance(opt, tuple) else opt for opt in options[i:i+2]]
        rows.append(current_options)

    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ================================================
#   START HANDLER
# ================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log.info(f"[NEW SESSION] User={chat_id} started bot")

    user_state[chat_id] = {"step": "stage"}
    log.info(f"[STATE INIT] {user_state[chat_id]}")

    cursor.execute("SELECT name FROM stages ORDER BY id ASC")
    stages = [row for row in cursor.fetchall()]
    log.info(f"[DB] Stages fetched: {stages}")

    await update.message.reply_text("اختر المرحلة:", reply_markup=make_keyboard(stages))


# ================================================
#   MAIN HANDLER
# ================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    log.info("\n============================")
    log.info(f"[USER MSG] Chat={chat_id} | Text='{text}'")

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]
    log.info(f"[CURRENT STATE] {state}")

    # ----------------------------------------------
    #   BACK BUTTON
    # ----------------------------------------------
    if text == "رجوع ↩️":
        log.info("[ACTION] BACK pressed")

        step = state.get("step")

        if step == "suboption":
            state["step"] = "option"
            cursor.execute("""
                SELECT subject_options.name
                FROM subject_option_map
                JOIN subject_options ON subject_options.id = subject_option_map.option_id
                WHERE subject_option_map.subject_id=?
            """, (state["subject_id"],))
            options = [o for o in cursor.fetchall()]
            return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(options))

        if step == "option":
            state["step"] = "subject"
            cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
            subjects = [s for s in cursor.fetchall()]
            return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(subjects))

        if step == "subject":
            state["step"] = "grade"
            cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
            grades = [g for g in cursor.fetchall()]
            return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(grades))

        if step == "grade":
            state["step"] = "term"
            cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
            terms = [t for t in cursor.fetchall()]
            return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(terms))

        if step == "term":
            state["step"] = "stage"
            cursor.execute("SELECT name FROM stages ORDER BY id ASC")
            stages = [s for s in cursor.fetchall()]
            return await update.message.reply_text("اختر المرحلة:", reply_markup=make_keyboard(stages))

        return await start(update, context)

    # --------------------------------------------------
    #   SELECT STAGE
    # --------------------------------------------------
    if state["step"] == "stage":
        log.info("[STEP] stage")

        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        log.info(f"[DB] stage lookup → {row}")

        if not row: return

        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (row[0],))
        terms = [t for t in cursor.fetchall()]
        log.info(f"[DB] Terms fetched: {terms}")

        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(terms))

    # --------------------------------------------------
    #   SELECT TERM  (FIXED!!)
    # --------------------------------------------------
    if state["step"] == "term":
        log.info("[STEP] term")

        cursor.execute(
            "SELECT id FROM terms WHERE name=? AND stage_id=?",
            (text, state["stage_id"])
        )
        row = cursor.fetchone()
        log.info(f"[DB] term lookup → {row}")

        if not row: return

        state["term_id"] = row[0]
        state["step"] = "grade"

        cursor.execute("SELECT name FROM grades WHERE term_id=?", (row[0],))
        grades = [g for g in cursor.fetchall()]
        log.info(f"[DB] Grades fetched: {grades}")

        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(grades))

    # --------------------------------------------------
    #   SELECT GRADE  (FIXED!!)
    # --------------------------------------------------
    if state["step"] == "grade":
        log.info("[STEP] grade")

        cursor.execute(
            "SELECT id FROM grades WHERE name=? AND term_id=?",
            (text, state["term_id"])
        )
        row = cursor.fetchone()
        log.info(f"[DB] grade lookup → {row}")

        if not row: return

        state["grade_id"] = row[0]
        state["step"] = "subject"

        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (row[0],))
        subjects = [s for s in cursor.fetchall()]
        log.info(f"[DB] Subjects fetched: {subjects}")

        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(subjects))

    # --------------------------------------------------
    #   SELECT SUBJECT  (FIXED!!)
    # --------------------------------------------------
    if state["step"] == "subject":
        log.info("[STEP] subject")

        cursor.execute(
            "SELECT id FROM subjects WHERE name=? AND grade_id=?",
            (text, state["grade_id"])
        )
        row = cursor.fetchone()
        log.info(f"[DB] subject lookup → {row}")

        if not row: return

        state["subject_id"] = row[0]
        state["step"] = "option"

        cursor.execute("""
            SELECT subject_options.name
            FROM subject_option_map
            JOIN subject_options ON subject_options.id = subject_option_map.option_id
            WHERE subject_option_map.subject_id=?
        """, (row[0],))
        options = [o for o in cursor.fetchall()]
        log.info(f"[DB] Options fetched: {options}")

        return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(options))

    # --------------------------------------------------
    #   SELECT OPTION
    # --------------------------------------------------
    if state["step"] == "option":
        log.info("[STEP] option")

        cursor.execute("SELECT id FROM subject_options WHERE name=?", (text,))
        row = cursor.fetchone()
        log.info(f"[DB] option lookup → {row}")

        if not row: return

        state["option_id"] = row[0]
        state["step"] = "suboption"

        cursor.execute("""
            SELECT option_children.name
            FROM subject_option_children_map
            JOIN option_children ON option_children.id = subject_option_children_map.child_id
            WHERE subject_option_children_map.subject_id=?
              AND option_children.option_id=? 
        """, (state["subject_id"], state["option_id"]))
        children = [o for o in cursor.fetchall()]
        log.info(f"[DB] Child options fetched: {children}")

        if not children:
            return await update.message.reply_text("❌ لا توجد خيارات فرعية.", reply_markup=make_keyboard([]))

        return await update.message.reply_text("اختر القسم الفرعي:", reply_markup=make_keyboard(children))

    # --------------------------------------------------
    #   SELECT SUBOPTION → RESOURCES
    # --------------------------------------------------
    if state["step"] == "suboption":
        log.info("[STEP] suboption")

        cursor.execute(
            "SELECT id FROM option_children WHERE name=? AND option_id=?",
            (text, state["option_id"])
        )
        row = cursor.fetchone()
        log.info(f"[DB] child lookup → {row}")

        if not row: return

        child_id = row[0]

        cursor.execute("""
            SELECT title, url
            FROM resources
            WHERE subject_id=? AND option_id=? AND child_id=?
        """, (state["subject_id"], state["option_id"], child_id))

        resources = cursor.fetchall()
        log.info(f"[DB] Resources fetched: {resources}")

        if not resources:
            return await update.message.reply_text("❌ لا يوجد محتوى.", reply_markup=make_keyboard([]))

        msg = "إليك المحتوى:\n\n"
        for title, url in resources:
            msg += f"▪️ <a href='{url}'>{title}</a>\n"

        return await update.message.reply_text(msg, reply_markup=make_keyboard([]), parse_mode="HTML", disable_web_page_preview=True)


# ============================
#   TELEGRAM & API SETUP
# ============================
app = FastAPI()
app.state.tg_application = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting bot app & DB schema check...")

    conn_init = sqlite3.connect(DB_PATH)
    cur = conn_init.cursor()
    cur.executescript("""
    PRAGMA foreign_keys = ON;
    """)
    conn_init.commit()
    conn_init.close()

    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.state.tg_application = tg_app

    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")

    async with tg_app:
        await tg_app.start()
        yield
        await tg_app.stop()


@app.post("/telegram")
async def telegram_webhook(request: Request):
    running_app = app.state.tg_application
    update = Update.de_json(await request.json(), running_app.bot)
    await running_app.process_update(update)
    return Response(status_code=200)


@app.get("/")
def read_root():
    return {"status": "OK"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
