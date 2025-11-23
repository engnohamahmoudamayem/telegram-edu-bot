# ============================
#   IMPORTS
# ============================
import os
import logging
import sqlite3
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
DB_PATH = "edu_bot_data.db"

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL is missing from environment variables!")


# ============================
#   LOGGING
# ============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("edu-bot")


# ============================
#   DATABASE HELPERS
# ============================
def db():
    return sqlite3.connect(DB_PATH)


def get_rows(query, args=()):
    conn = db()
    cur = conn.cursor()
    cur.execute(query, args)
    data = cur.fetchall()
    conn.close()

    rows, temp = [], []
    for item in data:
        temp.append(item[0])
        if len(temp) == 2:
            rows.append(temp)
            temp = []
    if temp:
        rows.append(temp)

    rows.append(["رجوع"])
    return rows


def get_file_url(subject, term, content_type, subcat):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT file_url FROM files
        WHERE subject_name=? AND term_name=?
        AND content_type_name=? AND subcategory_name=?
    """,
        (subject, term, content_type, subcat),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ============================
#   TELEGRAM BOT HANDLERS
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["step"] = "stage"

    rows = get_rows("SELECT name FROM stages")

    await update.message.reply_text(
        "📚 اختر المرحلة:",
        reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get("step", "stage")

    # رجوع
    if text == "رجوع":
        return await start(update, context)

    # ========== المرحلة ==========
    if step == "stage":
        context.user_data["stage"] = text
        context.user_data["step"] = "term"

        rows = get_rows("SELECT name FROM terms")
        return await update.message.reply_text(
            f"📘 اختر الفصل ({text}):",
            reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True),
        )

    # ========== الفصل ==========
    if step == "term":
        context.user_data["term"] = text
        context.user_data["step"] = "grade"

        rows = get_rows(
            "SELECT name FROM grades WHERE stage_name=?",
            (context.user_data["stage"],),
        )
        return await update.message.reply_text(
            "📘 اختر الصف:",
            reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True),
        )

    # ========== الصف ==========
    if step == "grade":
        context.user_data["grade"] = text
        context.user_data["step"] = "subject"

        rows = get_rows(
            "SELECT name FROM subjects WHERE grade_name=?",
            (text,),
        )
        return await update.message.reply_text(
            "📚 اختر المادة:",
            reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True),
        )

    # ========== المادة ==========
    if step == "subject":
        context.user_data["subject"] = text
        context.user_data["step"] = "content"

        rows = get_rows("SELECT name FROM content_types")
        return await update.message.reply_text(
            "📂 اختر نوع المحتوى:",
            reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True),
        )

    # ========== نوع المحتوى ==========
    if step == "content":
        context.user_data["content_type"] = text
        context.user_data["step"] = "subcategory"

        rows = get_rows(
            "SELECT name FROM content_subcategories WHERE content_type_name=?",
            (text,),
        )
        return await update.message.reply_text(
            f"📂 اختر ({text}):",
            reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True),
        )

    # ========== الفئة الفرعية ==========
    if step == "subcategory":
        stage = context.user_data["stage"]
        grade = context.user_data["grade"]
        term = context.user_data["term"]
        subject = context.user_data["subject"]
        content = context.user_data["content_type"]
        subcat = text

        url = get_file_url(subject, term, content, subcat)

        if url:
            return await update.message.reply_text(f"📎 الرابط:\n{url}")
        else:
            return await update.message.reply_text("⚠️ لا يوجد ملف لهذا الاختيار!")

    await update.message.reply_text("❗ استخدم الأزرار فقط")


# ============================
#   FASTAPI + WEBHOOK
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
