# ================================================
#   IMPORTS
# ================================================
import os
import sqlite3
import logging
from http import HTTPStatus
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from dotenv import load_dotenv

# ================================================
#   LOAD ENV
# ================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL")

print("🚀 BOT_TOKEN =", BOT_TOKEN)
print("🌍 APP_URL   =", APP_URL)

# ================================================
#   CHECK ENV
# ================================================
if not BOT_TOKEN or not APP_URL:
    print("❌ ERROR: ENV variables missing!")
    raise RuntimeError("BOT_TOKEN or APP_URL is missing!")

# ================================================
# DB SETUP
# ================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "edu_bot_data.db")

print("📌 DATABASE FILE =", DB_PATH)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ================================================
# LOGGING
# ================================================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("DEBUG-BOT")
log.info("🔥 BOT STARTING...")

# ================================================
# USER STATE MEMORY
# ================================================
user_state = {}

# ================================================
# KEYBOARD MAKER
# ================================================
def make_keyboard(options):
    rows = []
    for i in range(0, len(options), 2):
        current_options = [opt[0] if isinstance(opt, tuple) else opt for opt in options[i:i+2]]
        rows.append(current_options)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ================================================
# START HANDLER
# ================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🔥🔥 START HANDLER CALLED 🔥🔥")
    log.info("🔥🔥 START HANDLER CALLED 🔥🔥")

    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    cursor.execute("SELECT name FROM stages ORDER BY id ASC")
    stages = cursor.fetchall()
    print("🔍 STAGES =", stages)

    await update.message.reply_text("اختر المرحلة:", reply_markup=make_keyboard(stages))

# ================================================
# MESSAGE HANDLER
# ================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("💬 MESSAGE HANDLER CALLED")
    log.info("💬 MESSAGE HANDLER CALLED")

    chat_id = update.effective_chat.id
    text = update.message.text

    print(f"📩 User={chat_id} Sent='{text}'")
    log.info(f"[USER] {chat_id} → {text}")

    if chat_id not in user_state:
        return await start(update, context)

    # DEBUG SHOW STATE
    print("🔎 Current STATE:", user_state[chat_id])
    log.info(f"[STATE] {user_state[chat_id]}")

# ================================================
# FASTAPI SETUP
# ================================================
app = FastAPI()
app.state.tg_application = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 LIFESPAN START")
    log.info("🚀 LIFESPAN START")

    # build telegram app
    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.state.tg_application = tg_app

    # DEBUG WEBHOOK BEFORE SETTING
    info_before = await tg_app.bot.get_webhook_info()
    print("🔍 BEFORE SET WEBHOOK =", info_before)

    # SET WEBHOOK
    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")

    # DEBUG AFTER SETTING
    info_after = await tg_app.bot.get_webhook_info()
    print("🔍 AFTER SET WEBHOOK =", info_after)

    async with tg_app:
        await tg_app.start()
        yield
        await tg_app.stop()
        print("🛑 BOT STOPPED")
        log.info("🛑 BOT STOPPED")

app.router.lifespan_context = lifespan

# ================================================
# WEBHOOK ENDPOINT
# ================================================
@app.post("/telegram")
async def telegram_webhook(request: Request):
    print("📥 WEBHOOK RECEIVED!")
    log.info("📥 WEBHOOK RECEIVED!")

    try:
        body = await request.json()
        print("📨 RAW PAYLOAD:", body)
        log.info(f"📨 RAW PAYLOAD: {body}")
    except:
        print("❌ ERROR reading payload")
        return Response(status_code=400)

    running_app = app.state.tg_application
    if running_app is None:
        print("❌ Bot application NOT READY!")
        return Response(status_code=503)

    update = Update.de_json(body, running_app.bot)
    await running_app.process_update(update)
    return Response(status_code=200)

# ================================================
# ROOT ENDPOINT
# ================================================
@app.get("/")
def root():
    print("🌍 ROOT CALLED")
    return {"status": "Bot is running"}

# ================================================
# MAIN
# ================================================
if __name__ == "__main__":
    print("🚀 UVICORN RUNNING…")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
