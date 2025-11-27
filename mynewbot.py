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

    await update.message.reply_text(
        "اختر المرحلة:",
        reply_markup=make_keyboard(stages)
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

        retu
