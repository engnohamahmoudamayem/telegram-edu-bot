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

# ================================================
# DEBUG FUNCTION
# ================================================
def debug_sql(tag, query, params=()):
    print("\n==============================")
    print(f"🔍 DEBUG → {tag}")
    print("📌 QUERY:", query)
    print("📌 PARAMS:", params)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    print("📌 RESULT:", rows)
    print("==============================\n")
    return rows

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

    user_state[chat_id] = {"step": "stage"}

    stages = debug_sql(
        "GET_ALL_STAGES",
        "SELECT name FROM stages ORDER BY id ASC"
    )

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
        return await start(update, context)

    state = user_state[chat_id]

    # --------------------------------------------
    # زر الرجوع
    # --------------------------------------------
    if text == "رجوع ↩️":

        if state["step"] == "term":
            state["step"] = "stage"
            stages = debug_sql("BACK → GET STAGES", "SELECT name FROM stages")
            return await update.message.reply_text("اختر المرحلة:", reply_markup=make_keyboard(stages))

        if state["step"] == "grade":
            state["step"] = "term"
            terms = debug_sql(
                "BACK → GET TERMS",
                "SELECT name FROM terms WHERE stage_id=?",
                (state["stage_id"],)
            )
            return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(terms))

        if state["step"] == "subject":
            state["step"] = "grade"
            grades = debug_sql(
                "BACK → GET GRADES",
                "SELECT name FROM grades WHERE term_id=?",
                (state["term_id"],)
            )
            return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(grades))

        if state["step"] == "option":
            state["step"] = "subject"
            subjects = debug_sql(
                "BACK → GET SUBJECTS",
                "SELECT name FROM subjects WHERE grade_id=?",
                (state["grade_id"],)
            )
            return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(subjects))

        if state["step"] == "suboption":
            state["step"] = "option"
            options = debug_sql(
                "BACK → GET OPTIONS",
                """
                SELECT subject_options.name
                FROM subject_option_map
                JOIN subject_options
                    ON subject_options.id = subject_option_map.option_id
                WHERE subject_option_map.subject_id=?
                """,
                (state["subject_id"],)
            )
            return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(options))

        return await start(update, context)

    # --------------------------------------------
    # اختيار المرحلة
    # --------------------------------------------
    if state["step"] == "stage":

        row = debug_sql(
            "GET_STAGE_ID",
            "SELECT id FROM stages WHERE name=?",
            (text,)
        )

        if not row:
            return
        
        state["stage_id"] = row[0][0]
        state["step"] = "term"

        terms = debug_sql(
            "GET_TERMS_BY_STAGE",
            "SELECT name FROM terms WHERE stage_id=?",
            (state["stage_id"],)
        )

        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(terms))

    # --------------------------------------------
    # اختيار الفصل
    # --------------------------------------------
    if state["step"] == "term":

        row = debug_sql(
            "GET_TERM_ID",
            "SELECT id FROM terms WHERE name=? AND stage_id=?",
            (text, state["stage_id"])
        )

        if not row:
            return
        
        state["term_id"] = row[0][0]
        state["step"] = "grade"

        grades = debug_sql(
            "GET_GRADES_BY_TERM",
            "SELECT name FROM grades WHERE term_id=?",
            (state["term_id"],)
        )

        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(grades))

    # --------------------------------------------
    # اختيار الصف — تم إصلاحه + debug
    # --------------------------------------------
    if state["step"] == "grade":

        row = debug_sql(
            "GET_GRADE_ID",
            "SELECT id FROM grades WHERE name=? AND term_id=?",
            (text, state["term_id"])
        )

        if not row:
            return
        
        state["grade_id"] = row[0][0]
        state["step"] = "subject"

        subjects = debug_sql(
            "GET_SUBJECTS_BY_GRADE",
            "SELECT name FROM subjects WHERE grade_id=?",
            (state["grade_id"],)
        )

        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(subjects))

    # --------------------------------------------
    # اختيار المادة — تم إصلاحه + debug
    # --------------------------------------------
    if state["step"] == "subject":

        row = debug_sql(
            "GET_SUBJECT_ID",
            "SELECT id FROM subjects WHERE name=? AND grade_id=?",
            (text, state["grade_id"])
        )

        if not row:
            return
        
        state["subject_id"] = row[0][0]
        state["step"] = "option"

        options = debug_sql(
            "GET_OPTIONS",
            """
            SELECT subject_options.name
            FROM subject_option_map
            JOIN subject_options
                ON subject_options.id = subject_option_map.option_id
            WHERE subject_option_map.subject_id=?
            """,
            (state["subject_id"],)
        )

        return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(options))

    # --------------------------------------------
    # اختيار النوع — تم إصلاحه + debug
    # --------------------------------------------
    if state["step"] == "option":

        row = debug_sql(
            "GET_OPTION_ID",
            "SELECT id FROM subject_options WHERE name=?",
            (text,)
        )

        if not row:
            return
        
        state["option_id"] = row[0][0]
        state["step"] = "suboption"

        children = debug_sql(
            "GET_SUBOPTIONS",
            """
            SELECT option_children.name
            FROM subject_option_children_map
            JOIN option_children
               ON option_children.id = subject_option_children_map.child_id
            WHERE subject_option_children_map.subject_id=?
              AND option_children.option_id=?
            """,
            (state["subject_id"], state["option_id"])
        )

        return await update.message.reply_text("اختر القسم الفرعي:", reply_markup=make_keyboard(children))

    # --------------------------------------------
    # اختيار القسم الفرعي النهائي — debug
    # --------------------------------------------
    if state["step"] == "suboption":

        row = debug_sql(
            "GET_CHILD_ID",
            "SELECT id FROM option_children WHERE name=? AND option_id=?",
            (text, state["option_id"])
        )

        if not row:
            return
        
        child_id = row[0][0]

        resources = debug_sql(
            "GET_RESOURCES",
            """
            SELECT title, url
            FROM resources
            WHERE subject_id=? AND option_id=? AND child_id=?
            """,
            (state["subject_id"], state["option_id"], child_id)
        )

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
