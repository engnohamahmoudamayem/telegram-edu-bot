# ============================================================
#   IMPORTS & PATHS
# ============================================================
import os
import sqlite3
import logging
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

# === ENV VARS ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")

# === DB ===
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# === LOG ===
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("BOT")

# === USER STATE MEMORY ===
user_state = {}


# ============================================================
#   DEBUG HELPER
# ============================================================
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


# ============================================================
#   KEYBOARD MAKER
# ============================================================
def make_keyboard(options):
    rows = []
    for i in range(0, len(options), 2):
        row = [
            opt[0] if isinstance(opt, tuple) else opt
            for opt in options[i:i+2]
        ]
        rows.append(row)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ============================================================
#   START
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    stages = debug_sql("GET_STAGES", "SELECT name FROM stages ORDER BY id")

    welcome_text = (
    "👑✨ مرحباً بكم في *منصّة نيو أكاديمي* ✨👑\n"
    "-----------------------------------------\n"
    "📚 أكبر منصّة تعليمية شاملة للطلاب\n"
    "📘 مذكرات – 📝 اختبارات – 🎥 فيديوهات شرح\n"
    "-----------------------------------------\n"
    "💡 *اختر المرحلة للبدء:*"
)

await update.message.reply_text(
    welcome_text,
    reply_markup=make_keyboard(stages),
    parse_mode="Markdown"
)


# ============================================================
#   MESSAGE HANDLER
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    text = update.message.text

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]

    log.info(f"📩 USER CLICKED: {text}")

    # ========================================================
    #   رجوع
    # ========================================================
    if text == "رجوع ↩️":

        if state["step"] == "subchild":
            state["step"] = "suboption"
            cursor.execute("SELECT name FROM option_children WHERE option_id=?", (state["option_id"],))
            return await update.message.reply_text("اختر القسم:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "suboption":
            state["step"] = "option"
            cursor.execute("""
                SELECT subject_options.name
                FROM subject_option_map
                JOIN subject_options ON subject_options.id = subject_option_map.option_id
                WHERE subject_option_map.subject_id=?
            """, (state["subject_id"],))
            return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "option":
            state["step"] = "subject"
            cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
            return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "subject":
            state["step"] = "grade"
            cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
            return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "grade":
            state["step"] = "term"
            cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
            return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "term":
            state["step"] = "stage"
            cursor.execute("SELECT name FROM stages ORDER BY id")
            return await update.message.reply_text("اختر المرحلة:", reply_markup=make_keyboard(cursor.fetchall()))

        return await start(update, context)

    # ========================================================
    #   المرحلة
    # ========================================================
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return

        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall()))

    # ========================================================
    #   الفصل
    # ========================================================
    if state["step"] == "term":
        cursor.execute(
            "SELECT id FROM terms WHERE name=? AND stage_id=?",
            (text, state["stage_id"])
        )
        row = cursor.fetchone()
        if not row: return

        state["term_id"] = row[0]
        state["step"] = "grade"

        cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(cursor.fetchall()))

    # ========================================================
    #   الصف
    # ========================================================
    if state["step"] == "grade":
        cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return

        state["grade_id"] = row[0]
        state["step"] = "subject"

        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(cursor.fetchall()))

    # ========================================================
    #   المادة
    # ========================================================
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
        """, (state["subject_id"],))

        return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(cursor.fetchall()))

    # ========================================================
    #   OPTION (مذكرات – اختبارات – فيديوهات)
    # ========================================================
    if state["step"] == "option":

        cursor.execute("SELECT id FROM subject_options WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return

        state["option_id"] = row[0]
        state["step"] = "suboption"

        cursor.execute("SELECT name FROM option_children WHERE option_id=?", (state["option_id"],))
        children = cursor.fetchall()

        label = "اختر نوع المذكرات:" if state["option_id"] == 1 else "اختر القسم:"
        return await update.message.reply_text(label, reply_markup=make_keyboard(children))

    # ========================================================
    #   SUBOPTION
    # ========================================================
    if state["step"] == "suboption":

        option_id = state["option_id"]

        cursor.execute("SELECT id FROM option_children WHERE name=? AND option_id=?", (text, option_id))
        row = cursor.fetchone()
        if not row: return

        state["child_id"] = row[0]

        cursor.execute("SELECT name FROM option_subchildren WHERE child_id=?", (state["child_id"],))
        subs = cursor.fetchall()

        if subs:
            state["step"] = "subchild"
            return await update.message.reply_text("اختر القسم الفرعي:", reply_markup=make_keyboard(subs))

        cursor.execute("""
            SELECT title, url
            FROM resources
            WHERE subject_id=? AND option_id=? AND child_id=? AND (subchild_id IS NULL OR subchild_id=0)
        """, (state["subject_id"], option_id, state["child_id"]))

        resources = cursor.fetchall()

        if not resources:
            return await update.message.reply_text("لا يوجد محتوى حالياً.", reply_markup=make_keyboard([]))

        msg = "إليك المحتوى:\n\n" + "\n".join(
            [f"▪️ <a href='{u}'>{t}</a>" for t, u in resources]
        )

        return await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

    # ========================================================
    #   SUBCHILD (المذكرة الشاملة / ملخصات)
    # ========================================================
    if state["step"] == "subchild":

        cursor.execute("""
            SELECT id FROM option_subchildren WHERE name=? AND child_id=?
        """, (text, state["child_id"]))
        row = cursor.fetchone()
        if not row: return

        subchild_id = row[0]

        cursor.execute("""
            SELECT title, url
            FROM resources
            WHERE subject_id=? AND option_id=? AND child_id=? AND subchild_id=?
        """, (state["subject_id"], state["option_id"], state["child_id"], subchild_id))

        resources = cursor.fetchall()

        if not resources:
            return await update.message.reply_text("لا يوجد محتوى حالياً.", reply_markup=make_keyboard([]))

        msg = "إليك المحتوى:\n\n" + "\n".join(
            [f"▪️ <a href='{u}'>{t}</a>" for t, u in resources]
        )

        return await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)


# ============================================================
#   FASTAPI + TELEGRAM WEBHOOK
# ============================================================
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
