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
APP_URL = os.environ.get("APP_URL")
DB_PATH = "education_full.db"

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ Missing BOT_TOKEN or APP_URL")

# ============================
#   LOGGING
# ============================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edu_bot")

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
#   SUBJECT OPTIONS SYSTEM
# ============================
SUBJECT_OPTIONS = {
    "main": ["مذكرات", "اختبارات", "فيديوهات"],

    "مذكرات": ["مذكرات نيو", "مذكرات أخرى"],
    "مذكرات نيو": ["المذكرة الشاملة", "ملخصات"],

    "اختبارات": ["قصير أول", "قصير ثاني", "فاينال", "أوراق عمل"],
    "فيديوهات": ["مراجعة", "حل اختبارات"],
}

# ============================
#   FAKE LINKS FOR TEST
# ============================
FAKE_LINKS = {
    "المذكرة الشاملة": "https://example.com/full-note",
    "ملخصات": "https://example.com/summaries",

    "قصير أول": "https://example.com/quiz1",
    "قصير ثاني": "https://example.com/quiz2",
    "فاينال": "https://example.com/final",
    "أوراق عمل": "https://example.com/sheets",

    "مراجعة": "https:
