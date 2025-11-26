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
# تأكد من استخدام نفس الاسم الموجود في الـ Pre-Deploy command
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
#   DB CONNECTION (Global)
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
        # التأكد من أن القيمة المستخدمة هي النص فقط (row[0])
        current_options = [
            opt[0] if isinstance(opt, tuple) else opt
            for opt in options[i:i+2]
        ]
        rows.append(current_options)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ================================================
#   START HANDLER
# ================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    cursor.execute("SELECT name FROM stages ORDER BY id ASC")
    stages = cursor.fetchall()

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
        # إذا لم يكن المستخدم في أي حالة، ابدأ من جديد
        return await start(update, context)

    state = user_state[chat_id]

    # =============================
    # زر الرجوع ↩️
    # =============================
    if text == "رجوع ↩️":

        if state["step"] == "term":
            state["step"] = "stage"
            cursor.execute("SELECT name FROM stages")
            return await update.message.reply_text("اختر المرحلة:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "grade":
            state["step"] = "term"
            cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
            return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "subject":
            state["step"] = "grade"
            cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
            return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "option":
            state["step"] = "subject"
            cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
            return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(cursor.fetchall()))

        if state["step"] == "suboption":
            state["step"] = "option"
            cursor.execute("""
                SELECT subject_options.name
                FROM subject_option_map
                JOIN subject_options
                    ON subject_options.id = subject_option_map.option_id
                WHERE subject_option_map.subject_id=?
            """, (state["subject_id"],))
            return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(cursor.fetchall()))

        # fallback: العودة إلى البداية إذا لم تنطبق أي حالة
        return await start(update, context)


    # =============================
    # 1) اختيار المرحلة
    # =============================
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return

        state["stage_id"] = row[0] # تخزين الـ ID كقيمة مفردة
        state["step"] = "term"

        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 2) اختيار الفصل
    # =============================
    if state["step"] == "term":
        cursor.execute("SELECT id FROM terms WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return

        state["term_id"] = row[0] # تخزين الـ ID كقيمة مفردة
        state["step"] = "grade"

        # الاستعلام باستخدام الـ Term ID المخزن حديثاً
        cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 3) اختيار الصف
    # =============================
    if state["step"] == "grade":
        cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return

        state["grade_id"] = row[0] # تخزين الـ ID كقيمة مفردة
        state["step"] = "subject"

        # الاستعلام باستخدام الـ Grade ID المخزن حديثاً
        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 4) اختيار المادة
    # =============================
    if state["step"] == "subject":
        cursor.execute("SELECT id FROM subjects WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return

        state["subject_id"] = row[0] # تخزين الـ ID كقيمة مفردة
        state["step"] = "option"

        # الاستعلام باستخدام الـ Subject ID المخزن حديثاً
        cursor.execute("""
            SELECT subject_options.name
            FROM subject_option_map
            JOIN subject_options
               ON subject_options.id = subject_option_map.option_id
            WHERE subject_option_map.subject_id=?
        """, (state["subject_id"],))
        return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(cursor.fetchall()))

    # =============================
    # 5) اختيار نوع المحتوى (مذكرات/اختبارات)
    # =============================
    if state["step"] == "option":
        cursor.execute("SELECT id FROM subject_options WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return

        state["option_id"] = row[0] # تخزين الـ ID كقيمة مفردة
        state["step"] = "suboption"

        # الاستعلام باستخدام الـ Subject ID والـ Option ID (هنا كان الخطأ المنطقي سابقاً)
        cursor.execute("""
            SELECT option_children.name
            FROM subject_option_children_map
            JOIN option_children
               ON option_children.id = subject_option_children_map.child_id
            WHERE subject_option_children_map.subject_id=?
              AND option_children.option_id=?
        """, (state["subject_id"], state["option_id"]))
        
        children = cursor.fetchall()
        if not children:
             await update.message.reply_text("عذرًا، لا يوجد أقسام فرعية لهذا المحتوى حاليًا.", reply_markup=make_keyboard([]))
             return

        return await update.message.reply_text("اختر القسم الفرعي:", reply_markup=make_keyboard(children))

    # =============================
    # 6) اختيار القسم الفرعي وإظهار المحتوى
    # =============================
    if state["step"] == "suboption":
        cursor.execute("""
            SELECT id FROM option_children
            WHERE name=? AND option_id=?
        """, (text, state["option_id"]))
        row = cursor.fetchone()
        if not row: return

        child_id = row[0] # تخزين الـ ID كقيمة مفردة

        # الاستعلام النهائي عن المصادر
        cursor.execute("""
            SELECT title, url
            FROM resources
            WHERE subject_id=?
              AND option_id=?
              AND child_id=?
        """, (state["subject_id"], state["option_id"], child_id))

        resources = cursor.fetchall()

        if not resources:
            await update.message.reply_text(
                "عذرًا، لا يوجد محتوى مطابق حاليًا.",
                reply_markup=make_keyboard([])
            )
            return

        response_text = "إليك المحتوى المتوفر:\n\n"
        for title, url in resources:
            response_text += f"▪️ <a href='{url}'>{title}</a>\n"

        await update.message.reply_text(
            response_text,
            reply_markup=make_keyboard([]),
            parse_mode='HTML',
            disable_web_page_preview=True
        )


# ============================
#   TELEGRAM & FastAPI SETUP
# ============================

app = FastAPI()
app.state.tg_application = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes database schema and Telegram bot application lifecycle."""
    log.info("Starting up bot application and initializing DB...")
    
    # --- Database Initialization (Ensures schema is present on startup) ---
    # هذا الجزء يضمن إنشاء الجداول إذا لم تكن موجودة عند تشغيل التطبيق على Render
    try:
        conn_init = sqlite3.connect(DB_PATH)
        cur = conn_init.cursor()
        cur.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS stages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS terms (id INTEGER PRIMARY KEY AUTOINCREMENT, stage_id INTEGER NOT NULL, name TEXT NOT NULL, FOREIGN KEY(stage_id) REFERENCES stages(id));
        CREATE TABLE IF NOT EXISTS grades (id INTEGER PRIMARY KEY AUTOINCREMENT, term_id INTEGER NOT NULL, name TEXT NOT NULL, FOREIGN KEY(term_id) REFERENCES terms(id));
        CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, grade_id INTEGER NOT NULL, name TEXT NOT NULL, FOREIGN KEY(grade_id) REFERENCES grades(id));
        CREATE TABLE IF NOT EXISTS subject_options (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS option_children (id INTEGER PRIMARY KEY AUTOINCREMENT, option_id INTEGER NOT NULL, name TEXT NOT NULL, FOREIGN KEY(option_id) REFERENCES subject_options(id));
        CREATE TABLE IF NOT EXISTS subject_option_map (id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER NOT NULL, option_id INTEGER NOT NULL, FOREIGN KEY(subject_id) REFERENCES subjects(id), FOREIGN KEY(option_id) REFERENCES subject_options(id));
        CREATE TABLE IF NOT EXISTS subject_option_children_map (id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER NOT NULL, child_id INTEGER NOT NULL, FOREIGN KEY(subject_id) REFERENCES subjects(id), FOREIGN KEY(child_id) REFERENCES option_children(id));
        CREATE TABLE IF NOT EXISTS resources (id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER NOT NULL, option_id INTEGER NOT NULL, child_id INTEGER NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL, description TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(subject_id) REFERENCES subjects(id), FOREIGN KEY(option_id) REFERENCES subject_options(id), FOREIGN KEY(child_id) REFERENCES option_children(id));
        """)
        conn_init.commit()
        conn_init.close()
        print("✔ DB schema ensured!")
    except Exception as e:
        log.error(f"Failed to initialize database within lifespan: {e}")
        raise

    # --- Telegram Bot Setup ---
    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.state.tg_application = tg_app

    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")
    async with tg_app:
        await tg_app.start()
        yield
        await tg_app.stop()
        log.info("Shutting down bot application.")


app.router.lifespan_context = lifespan


@app.post("/telegram")
async def telegram_webhook(request: Request):
    """Handles incoming Telegram webhooks."""
    running_app = app.state.tg_application
    if running_app is None:
        return Response(status_code=HTTPStatus.SERVICE_UNAVAILABLE)

    update = Update.de_json(await request.json(), running_app.bot)
    await running_app.process_update(update)
    return Response(status_code=HTTPStatus.OK)


@app.get("/")
def read_root():
    return {"status": "Service is running"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
