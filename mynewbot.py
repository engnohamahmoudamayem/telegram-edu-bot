# ============================================================
#   IMPORTS & PATHS
# ============================================================
import os
import sqlite3
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

# ============================================================
#   ENV & DB
# ============================================================
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "edu_bot_data.db")
print("📌 DATABASE LOCATION =", DB_PATH)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("BOT")

user_state = {}

# ============================================================
#   KEYBOARD MAKER — RTL
# ============================================================
def make_keyboard(options):
    rows = []
    for i in range(0, len(options), 2):
        row = [
            opt[0] if isinstance(opt, tuple) else opt
            for opt in options[i:i + 2]
        ]
        row.reverse()
        rows.append(row)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ============================================================
#   START COMMAND
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    welcome = (
        "✨ *منصة نيو أكاديمي التعليمية* ✨\n"
        "مرحباً بكم في منصتكم التعليمية ❤️\n\n"
        "📚 *اختر المرحلة للبدء:*"
    )

    cursor.execute("SELECT name FROM stages ORDER BY id")
    stages = cursor.fetchall()

    await update.message.reply_text(
        welcome,
        reply_markup=make_keyboard(stages),
        parse_mode="Markdown"
    )

# ============================================================
#   MAIN BOT HANDLER
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    text = update.message.text

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]
    log.info(f"📩 USER CLICKED: {text}")

    # ---------------- زر الرجوع ----------------
    if text == "رجوع ↩️":

        order = [
            "subchild", "suboption", "option",
            "subject", "grade", "term", "stage"
        ]

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

    # ---------------- المرحلة ----------------
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["stage_id"] = row[0]
        state["step"] = "term"
        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall()))

    # ---------------- الفصل ----------------
    if state["step"] == "term":
        cursor.execute("SELECT id FROM terms WHERE name=? AND stage_id=?", (text, state["stage_id"]))
        row = cursor.fetchone()
        if not row: return
        state["term_id"] = row[0]
        state["step"] = "grade"
        cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(cursor.fetchall()))

    # ---------------- الصف ----------------
    if state["step"] == "grade":
        cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["grade_id"] = row[0]
        state["step"] = "subject"
        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(cursor.fetchall()))

    # ---------------- المادة ----------------
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

    # ---------------- OPTION ----------------
    if state["step"] == "option":
        cursor.execute("SELECT id FROM subject_options WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row: return
        state["option_id"] = row[0]
        state["step"] = "suboption"
        cursor.execute("SELECT name FROM option_children WHERE option_id=?", (state["option_id"],))
        return await update.message.reply_text("اختر القسم:", reply_markup=make_keyboard(cursor.fetchall()))

    # ---------------- SUBOPTION ----------------
    if state["step"] == "suboption":

        cursor.execute("SELECT id FROM option_children WHERE name=? AND option_id=?", (text, state["option_id"]))
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
            WHERE subject_id=? AND option_id=? AND child_id=?
              AND (subchild_id IS NULL OR subchild_id=0)
        """, (state["subject_id"], state["option_id"], state["child_id"]))

        resources = cursor.fetchall()

        if not resources:
            return await update.message.reply_text("لا يوجد محتوى.")

        msg = "\n".join(f"▪️ <a href='{u}'>{t}</a>" for t, u in resources)
        return await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

    # ---------------- SUBCHILD ----------------
    if state["step"] == "subchild":

        cursor.execute("SELECT id FROM option_subchildren WHERE name=? AND child_id=?", (text, state["child_id"]))
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
            return await update.message.reply_text("لا يوجد محتوى.")

        msg = "\n".join(f"▪️ <a href='{u}'>{t}</a>" for t, u in resources)
        return await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

# ============================================================
#   FASTAPI — TELEGRAM WEBHOOK
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

# ============================================================
#   ADMIN PANEL HTML
# ============================================================
def _fetch_all(query, params=()):
    cursor.execute(query, params)
    return cursor.fetchall()

@app.get("/admin", response_class=HTMLResponse)
def admin_form():

    subjects = _fetch_all("SELECT id, name FROM subjects")
    options = _fetch_all("SELECT id, name FROM subject_options")
    children = _fetch_all("SELECT id, name, option_id FROM option_children")
    subchildren = _fetch_all("SELECT id, name, child_id FROM option_subchildren")
    resources = _fetch_all("""
        SELECT id, title, url, subject_id, option_id, child_id, subchild_id
        FROM resources ORDER BY id DESC LIMIT 100
    """)

    return f"""
    <html lang='ar' dir='rtl'>
    <head>
        <meta charset='utf-8'>
        <title>لوحة تحكم نيو أكاديمي</title>
        <style>
            body {{
                font-family: sans-serif;
                background: #eef2f7;
                padding: 20px;
            }}
            .box {{
                background: white;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(0,0,0,.1);
            }}
            input {{
                padding: 8px;
                width: 100%;
                margin-top: 4px;
                margin-bottom: 10px;
                border-radius: 8px;
                border: 1px solid #ccc;
            }}
            button {{
                padding: 10px 16px;
                background: #1976d2;
                color: white;
                border: none;
                border-radius: 8px;
                cursor: pointer;
            }}
        </style>
    </head>

    <body>
        <h1>✨ لوحة تحكم نيو أكاديمي</h1>

        <div class='box'>
            <h2>➕ إضافة رابط</h2>
            <form method='post' action='/admin/add'>
                <label>كلمة المرور:</label>
                <input type='password' name='password' required>

                <label>العنوان:</label>
                <input type='text' name='title' required>

                <label>الرابط:</label>
                <input type='url' name='url' required>

                <label>subject_id:</label>
                <input type='number' name='subject_id' required>

                <label>option_id:</label>
                <input type='number' name='option_id' required>

                <label>child_id:</label>
                <input type='number' name='child_id' required>

                <label>subchild_id (اختياري):</label>
                <input type='number' name='subchild_id'>

                <button>حفظ</button>
            </form>
        </div>

        <div class='box'>
            <h2>📄 رفع PDF</h2>
            <form method='post' action='/admin/upload' enctype='multipart/form-data'>
                <label>كلمة المرور:</label>
                <input type='password' name='password' required>

                <label>subject_id:</label>
                <input type='number' name='subject_id' required>

                <label>option_id:</label>
                <input type='number' name='option_id' required>

                <label>child_id:</label>
                <input type='number' name='child_id' required>

                <label>subchild_id (اختياري):</label>
                <input type='number' name='subchild_id'>

                <label>ملف PDF:</label>
                <input type='file' name='file' accept='.pdf' required>

                <button>رفع</button>
            </form>
        </div>
    </body>
    </html>
    """

# ============================================================
#   ADD LINK
# ============================================================
@app.post("/admin/add")
def admin_add(
    password: str = Form(...),
    title: str = Form(...),
    url: str = Form(...),
    subject_id: int = Form(...),
    option_id: int = Form(...),
    child_id: int = Form(...),
    subchild_id: int | None = Form(None),
):
    if password != ADMIN_PASSWORD:
        return HTMLResponse("❌ كلمة المرور غلط", status_code=401)

    cursor.execute("""
        INSERT INTO resources (subject_id, option_id, child_id, subchild_id, title, url)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (subject_id, option_id, child_id, subchild_id, title, url))

    conn.commit()
    return RedirectResponse("/admin", status_code=303)

# ============================================================
#   PDF UPLOAD
# ============================================================
@app.post("/admin/upload")
async def admin_upload(
    password: str = Form(...),
    subject_id: int = Form(...),
    option_id: int = Form(...),
    child_id: int = Form(...),
    subchild_id: int = Form(None),
    file: UploadFile = File(...)
):
    if password != ADMIN_PASSWORD:
        return HTMLResponse("❌ كلمة المرور غلط", status_code=401)

    upload_dir = os.path.join(BASE_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    file_url = f"{APP_URL}/files/{file.filename}"

    cursor.execute("""
        INSERT INTO resources (subject_id, option_id, child_id, subchild_id, title, url)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (subject_id, option_id, child_id, subchild_id, file.filename, file_url))

    conn.commit()
    return RedirectResponse("/admin", status_code=303)

# ============================================================
#   SERVE PDF FILES
# ============================================================
@app.get("/files/{filename}")
async def serve_file(filename: str):
    file_path = os.path.join(BASE_DIR, "uploads", filename)
    if not os.path.exists(file_path):
        return Response("File Not Found", status_code=404)

    return Response(open(file_path, "rb").read(), media_type="application/pdf")
