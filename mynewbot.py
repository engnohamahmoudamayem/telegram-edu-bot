# ============================
#   IMPORTS
# ============================
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "education_full.db")

print("📌 DATABASE LOCATION =", DB_PATH)

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
#   GENERIC KEYBOARD MAKER
# ============================
def make_keyboard(options):
    rows = []

    # 2 buttons per row
    for i in range(0, len(options), 2):
        rows.append(options[i:i+2])

    # BACK button in its own row
    rows.append(["رجوع ↩️"])

    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ============================
#   /START
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    # Get stages
    cursor.execute("SELECT name FROM stages")
    stages = [row[0] for row in cursor.fetchall()]

    # ORDER: الابتدائية → المتوسطة → الثانوية
    order = ["الابتدائية", "المتوسطة", "الثانوية"]
    stages = order

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

    # Handle BACK
    if text == "رجوع ↩️":
        state = user_state.get(chat_id, {})
        step = state.get("step", "")

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
            terms.reverse()  # الفصل الثاني يمين
            return await update.message.reply_text(
                "اختر الفصل:",
                reply_markup=make_keyboard(terms)
            )

        if step == "subject":
            state["step"] = "grade"
            cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
            grades = [g[0] for g in cursor.fetchall()]
            return await update.message.reply_text(
                "اختر الصف:",
                reply_markup=make_keyboard(grades)
            )

        if step == "option":
            state["step"] = "subject"
            cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
            subjects = [s[0] for s in cursor.fetchall()]
            return await update.message.reply_text(
                "اختر المادة:",
                reply_markup=make_keyboard(subjects)
            )

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
                reply_markup=make_keyboard(options)
            )

        return await start(update, context)

    # reset if needed
    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]

    # ============================
    #   SELECT STAGE
    # ============================
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (row[0],))
        terms = [t[0] for t in cursor.fetchall()]

        # الفصل الثاني يمين
        terms.reverse()

        return await update.message.reply_text(
            "اختر الفصل:",
            reply_markup=make_keyboard(terms)
        )

    # ============================
    #   SELECT TERM
    # ============================
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
            reply_markup=make_keyboard(grades)
        )

    # ============================
    #   SELECT GRADE
    # ============================
   # -------------------------
#   STEP: GRADE
# -------------------------
if state["step"] == "grade":
    cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
    row = cursor.fetchone()
    if not row:
        return

    state["grade_id"] = row[0]
    state["step"] = "subject"

    # =====================================================
    #   ترتيب الصفوف يدوي حسب المرحلة
    # =====================================================
    stage_id = state["stage_id"]

    # ---------------------- ابتدائي -----------------------
    if stage_id == 1:   # المرحلة الابتدائية
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

    # ---------------------- متوسط -----------------------
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

    # ---------------------- ثانوي -----------------------
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
    #   SELECT SUBJECT
    # ============================
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
            reply_markup=make_keyboard(options)
        )

    # ============================
    #   SELECT CONTENT OPTION
    # ============================
      # ============================
    #   SELECT CONTENT OPTION
    # ============================
    if state["step"] == "option":
        cursor.execute("SELECT id FROM subject_options WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["option_id"] = row[0]
        state["step"] = "suboption"

        # VVVV هذا هو الاستعلام المصحح VVVV
        cursor.execute("""
            SELECT option_children.name
            FROM subject_option_children_map
            JOIN option_children ON option_children.id = subject_option_children_map.child_id
            WHERE subject_option_children_map.subject_id=?
              AND option_children.option_id=?
        """, (state["subject_id"], state["option_id"])) 
        # ^^^^ استخدمنا state["option_id"] هنا ^^^^

        children = [c[0] for c in cursor.fetchall()]
        # ... (بقية الكود لعرض لوحة المفاتيح) ...


        return await update.message.reply_text(
            "اختر القسم الفرعي:",
            reply_markup=make_keyboard(children)
        )

    # ============================
    #   SHOW RESOURCES
    # ============================
    if state["step"] == "suboption":

        cursor.execute("SELECT id FROM option_children WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return await update.message.reply_text("❌ القسم غير موجود!")
        child_id = row[0]

        subject_id = state["subject_id"]
        option_id = state["option_id"]

        cursor.execute("""
            SELECT title, url
            FROM resources
            WHERE subject_id=? AND option_id=? AND child_id=?
        """, (subject_id, option_id, child_id))

        data = cursor.fetchall()

        if not data:
            return await update.message.reply_text("❌ لا يوجد محتوى حتى الآن.")

        msg = "📘 *المحتوى المتاح:*\n\n"
        for t, u in data:
            msg += f"📌 *{t}*\n🔗 {u}\n\n"

        return await update.message.reply_text(msg, parse_mode="Markdown")


# ============================
#   TELEGRAM / FASTAPI
# ============================
ptb_app = Application.builder().token(BOT_TOKEN).updater(None).build()
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
