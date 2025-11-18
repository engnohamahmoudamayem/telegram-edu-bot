import os
import logging
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv

# Load environment variables (useful for local testing)
load_dotenv() 

# ======================
#   ENVIRONMENT VARS & LOGGING
# ======================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edu-bot")

# ======================
#   HANDLERS (Keep your existing async handlers)
# ======================
async def start(update: Update, context):
    await update.message.reply_text("البوت اشتغل بنجاح ✔️")

async def handle_message(update: Update, context):
    await update.message.reply_text("استخدمي الأزرار 👇")

# ======================
#   FASTAPI INTEGRATION
# ======================

# Initialize the PTB application builder
ptb_app = (
    Application.builder()
    .token(BOT_TOKEN)
    .updater(None)  # We don't use the built-in updater/webhook runner
    .build()
)

# Add your handlers
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# Define the lifespan manager for FastAPI to start/stop the bot gracefully
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set the webhook URL when the app starts up
    await ptb_app.bot.set_webhook(url=f"{APP_URL}/webhook")
    async with ptb_app:
        yield


# Initialize FastAPI app with the lifespan manager
app = FastAPI(lifespan=lifespan)

# Define the endpoint where Telegram will send updates (must match APP_URL/webhook)
@app.post("/webhook")
async def telegram_webhook(request: Request):
    # Process the update using the PTB application
    update_json = await request.json()
    update = Update.de_json(update_json, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=HTTPStatus.OK)

# This script only defines the FastAPI app; it doesn't run a server itself.
# The 'uvicorn' command on Render runs the server.
