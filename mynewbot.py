import os
import logging
import sqlite3
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, Request, Response
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# Load environment variables (useful for local testing)
load_dotenv() 

# ======================
#   ENVIRONMENT VARS & LOGGING
# ======================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
DB_PATH = os.environ.get("DATABASE_PATH", "edu_bot_data.db") 

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("edu-bot")

# ======================
#   DATABASE FUNCTIONS
# ======================

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row # Allows accessing rows by column name
    return conn

def setup_database():
    """Creates the menu table if it doesn't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_text TEXT NOT NULL,
            link_url TEXT,
            parent_menu_text TEXT NOT NULL
        )
    ''')
    conn.commit()
    # Ensure 'main' entry exists for basic handling
    cursor.execute("SELECT id FROM menu_items WHERE menu_text = ?", ("main",))
    if not cursor.fetchone():
         cursor.execute("INSERT INTO menu_items (menu_text, parent_menu_text) VALUES (?, ?)", ("main", "root"))
         conn.commit()
    conn.close()

def get_menu_items(parent_text):
    """Fetches all items belonging to a specific parent menu."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT menu_text, link_url FROM menu_items WHERE parent_menu_text = ?", 
        (parent_text,)
    )
    items = cursor.fetchall()
    conn.close()
    # Format items into rows for the keyboard helper
    rows = []
    temp_row = []
    for item in items:
        temp_row.append(item['menu_text'])
        if len(temp_row) == 3:
            rows.append(temp_row)
            temp_row = []
    if temp_row:
        rows.append(temp_row)
        
    return rows

def get_item_details(menu_text):
    """Fetches details for a specific menu item."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT link_url, parent_menu_text FROM menu_items WHERE menu_text = ?", 
        (menu_text,)
    )
    item = cursor.fetchone()
    conn.close()
    return item

# ======================
#   KEYBOARD HELPER & HANDLERS
# ======================

def kb(rows):
    """Helper to format rows into ReplyKeyboardMarkup."""
    # We add a back button to any menu that isn't the 'main' menu structure
    # This check is heuristic and might need fine tuning depending on DB structure
    if rows and not any("الثانوية" in r for r in rows): 
       rows.append(["رجوع"])
       
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def send_menu(update: Update, context, menu_name, reply_text):
    """Helper to fetch and send a menu from the DB."""
    rows = get_menu_items(menu_name)
    if not rows and menu_name != 'main':
        await update.message.reply_text("هذه الفئة فارغة حالياً.", reply_markup=kb([["رجوع"]]))
    else:
        await update.message.reply_text(reply_text, reply_markup=kb(rows))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command, shows main menu."""
    context.user_data.clear()
    context.user_data["current"] = "main"
    await send_menu(update, context, 'main', "من فضلك اختر المرحلة:")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages and menu navigation."""
    text = update.message.text.strip()
    current_menu_name = context.user_data.get("current", "main")
    
    # Handle 'رجوع' button dynamically
    if text == "رجوع":
        item_details = get_item_details(current_menu_name)
        if item_details and item_details['parent_menu_text'] != 'root':
            parent_name = item_details['parent_menu_text']
            context.user_data["current"] = parent_name
            return await send_menu(update, context, parent_name, f"عُدنا إلى {parent_name}")
        else:
            return await send_menu(update, context, 'main', "أنت الآن في القائمة الرئيسية.")

    # Check if the text matches an existing menu item name or link
    item_details = get_item_details(text)

    if item_details:
        if item_details['link_url']:
            # If it has a URL, send the link directly
            return await update.message.reply_text(f"🔗 الرابط:\n{item_details['link_url']}")
        else:
            # If it doesn't have a URL, it's a submenu, so display that menu
            context.user_data["current"] = text
            return await send_menu(update, context, text, f"📚 اختر من قائمة {text}:")

    return await update.message.reply_text("❗ استخدم الأزرار 👇")


# ======================
#   FASTAPI INTEGRATION & BOT SETUP
# ======================

# Setup database file on application start
setup_database()

if not BOT_TOKEN or not APP_URL:
    log.error("Missing BOT_TOKEN or APP_URL environment variables!")
    raise RuntimeError("Environment variables not configured.") 

# Initialize the PTB application builder
ptb_app = (
    Application.builder()
    .token(BOT_TOKEN)
    .updater(None)
    .build()
)

# Add handlers
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set the webhook URL when the app starts up
    await ptb_app.bot.set_webhook(url=f"{APP_URL}/webhook")
    async with ptb_app:
        yield

# Initialize FastAPI app with the lifespan manager
app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def telegram_webhook(request: Request):
    update_json = await request.json()
    update = Update.de_json(update_json, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=HTTPStatus.OK)
