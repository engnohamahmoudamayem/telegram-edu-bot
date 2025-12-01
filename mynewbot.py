# ============================================================
#   IMPORTS & PATHS
# ============================================================
import os
import uuid
import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
#   CONFIGURATION
# ============================================================
load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = BASE_DIR / "edu_bot_data.db"
UPLOAD_DIR = BASE_DIR / "uploads"
TEMPLATE_DIR = BASE_DIR / "templates"

UPLOAD_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR.mkdir(exist_ok=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")

# ============================================================
#   LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("EDU_BOT")

# ============================================================
#   DATABASE LAYER
# ============================================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    log.info("Initializing database...")
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            stage_id INTEGER NOT NULL,
            FOREIGN KEY (stage_id) REFERENCES stages(id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            term_id INTEGER NOT NULL,
            FOREIGN KEY (term_id) REFERENCES terms(id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            grade_id INTEGER NOT NULL,
            FOREIGN KEY (grade_id) REFERENCES grades(id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subject_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subject_option_map (
            subject_id INTEGER NOT NULL,
            option_id INTEGER NOT NULL,
            PRIMARY KEY (subject_id, option_id),
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            FOREIGN KEY (option_id) REFERENCES subject_options(id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS option_children (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            option_id INTEGER NOT NULL,
            FOREIGN KEY (option_id) REFERENCES subject_options(id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS option_subchildren (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            child_id INTEGER NOT NULL,
            FOREIGN KEY (child_id) REFERENCES option_children(id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            stage_id INTEGER,
            term_id INTEGER,
            grade_id INTEGER,
            subject_id INTEGER,
            option_id INTEGER,
            child_id INTEGER,
            subchild_id INTEGER,
            FOREIGN KEY (stage_id) REFERENCES stages(id),
            FOREIGN KEY (term_id) REFERENCES terms(id),
            FOREIGN KEY (grade_id) REFERENCES grades(id),
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            FOREIGN KEY (option_id) REFERENCES subject_options(id),
            FOREIGN KEY (child_id) REFERENCES option_children(id),
            FOREIGN KEY (subchild_id) REFERENCES option_subchildren(id)
        )
        """)

        conn.commit()

init_db()

# ============================================================
#   USER STATE
# ============================================================
user_state: Dict[int, Dict[str, Any]] = {}

# ============================================================
#   HELPER FUNCTIONS
# ============================================================
def make_keyboard(options):
    rows = []
    for i in range(0, len(options), 2):
        row = [opt[0] if isinstance(opt, tuple) else opt for opt in options[i:i+2]]
        row.reverse()
        rows.append(row)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def fetch_all(query, params=()):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

def fetch_one(query, params=()):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
# ============================================================
#   FILE UPLOAD HANDLER
# ============================================================
async def save_uploaded_file(file: UploadFile) -> Optional[str]:
    if not file or not file.filename:
        return None

    try:
        ext = Path(file.filename).suffix
        unique_name = f"{uuid.uuid4()}{ext}"
        save_path = UPLOAD_DIR / unique_name

        content = await file.read()
        save_path.write_bytes(content)

        return f"{APP_URL}/files/{unique_name}"

    except Exception as e:
        log.error(f"Error saving file: {e}")
        return None

# ============================================================
#   SEND RESOURCES TO USER
# ============================================================
async def send_resources(update: Update, state: dict):
    try:
        rows = fetch_all(
            """
            SELECT title, url FROM resources
            WHERE stage_id=? AND term_id=? AND grade_id=?
              AND subject_id=? AND option_id=? AND child_id=?
              AND (subchild_id = ? OR subchild_id IS NULL)
            """,
            (
                state["stage_id"], state["term_id"], state["grade_id"],
                state["subject_id"], state["option_id"], state["child_id"],
                state.get("subchild_id"),
            ),
        )

        if not rows:
            await update.message.reply_text("لا يوجد محتوى حالياً.")
            return

        msg = "\n".join(f"▪️ <a href='{r['url']}'>{r['title']}</a>" for r in rows)
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        log.error(f"Error sending resources: {e}")
        await update.message.reply_text("حدث خطأ أثناء عرض المحتوى.")

# ============================================================
#   TELEGRAM BOT HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    stages = fetch_all("SELECT id, name FROM stages ORDER BY id")
    stage_names = [(s["name"],) for s in stages]

    await update.message.reply_text(
        "✨ *منصة نيو أكاديمي التعليمية* ✨\nاختر المرحلة:",
        reply_markup=make_keyboard(stage_names),
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]

    # ====================== زر الرجوع ======================
    if text == "رجوع ↩️":
        order = [
            "subchild", "suboption", "option",
            "subject", "grade", "term"
        ]
        for step in order:
            if state.get("step") == step:
                prev_steps = {
                    "subchild": ("suboption", "SELECT name FROM option_children WHERE option_id=?", (state["option_id"],), "اختر القسم:"),
                    "suboption": ("option", "SELECT so.name FROM subject_option_map som JOIN subject_options so ON so.id=som.option_id WHERE som.subject_id=?", (state["subject_id"],), "اختر نوع المحتوى:"),
                    "option": ("subject", "SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],), "اختر المادة:"),
                    "subject": ("grade", "SELECT name FROM grades WHERE term_id=?", (state["term_id"] ), "اختر الصف:"),
                    "grade": ("term", "SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],), "اختر الفصل:"),
                    "term": ("stage", "SELECT name FROM stages ORDER BY id", (), "اختر المرحلة:"),
                }

                new_step, query, params, msg = prev_steps[step]
                state["step"] = new_step
                options = fetch_all(query, params)
                await update.message.reply_text(msg, reply_markup=make_keyboard(options))
                return

        return await start(update, context)

    # ====================== مرحلة → فصل ======================
    if state["step"] == "stage":
        row = fetch_one("SELECT id FROM stages WHERE name=?", (text,))
        if not row:
            return
        state["stage_id"] = row["id"]
        state["step"] = "term"

        terms = fetch_all("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(terms))

    # ====================== فصل → صف ======================
    if state["step"] == "term":
        row = fetch_one("SELECT id FROM terms WHERE name=? AND stage_id=?", (text, state["stage_id"]))
        if not row:
            return

        state["term_id"] = row["id"]
        state["step"] = "grade"

        grades = fetch_all("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(grades))

    # ====================== صف → مادة ======================
    if state["step"] == "grade":
        row = fetch_one("SELECT id FROM grades WHERE name=?", (text,))
        if not row:
            return

        state["grade_id"] = row["id"]
        state["step"] = "subject"

        subjects = fetch_all("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(subjects))

    # ====================== مادة → نوع المحتوى ======================
    if state["step"] == "subject":
        row = fetch_one("SELECT id FROM subjects WHERE name=?", (text,))
        if not row:
            return

        state["subject_id"] = row["id"]
        state["step"] = "option"

        opts = fetch_all("""
            SELECT so.name
            FROM subject_option_map som
            JOIN subject_options so ON so.id = som.option_id
            WHERE som.subject_id=?
        """, (state["subject_id"],))

        return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(opts))

    # ====================== نوع المحتوى → Child ======================
    if state["step"] == "option":
        row = fetch_one("SELECT id FROM subject_options WHERE name=?", (text,))
        if not row:
            return

        state["option_id"] = row["id"]
        state["step"] = "suboption"

        children = fetch_all("SELECT name FROM option_children WHERE option_id=?", (state["option_id"],))
        return await update.message.reply_text("اختر القسم:", reply_markup=make_keyboard(children))

    # ====================== Child → SubChild أو محتوى ======================
    if state["step"] == "suboption":
        row = fetch_one("SELECT id FROM option_children WHERE name=? AND option_id=?", (text, state["option_id"]))
        if not row:
            return

        state["child_id"] = row["id"]

        subs = fetch_all("SELECT name FROM option_subchildren WHERE child_id=?", (state["child_id"],))
        if subs:
            state["step"] = "subchild"
            return await update.message.reply_text("اختر القسم الفرعي:", reply_markup=make_keyboard(subs))

        return await send_resources(update, state)

    # ====================== SubChild → موارد ======================
    if state["step"] == "subchild":
        row = fetch_one("SELECT id FROM option_subchildren WHERE name=? AND child_id=?", (text, state["child_id"]))
        if not row:
            return

        state["subchild_id"] = row["id"]
        return await send_resources(update, state)
# ============================================================
#   FASTAPI — TELEGRAM WEBHOOK
# ============================================================
app = FastAPI(title="Edu Bot API")

# Serve uploaded files
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Telegram application...")

    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")
    app.state.tg_application = tg_app

    async with tg_app:
        await tg_app.start()
        yield
        await tg_app.stop()

    log.info("Application shutdown complete.")

app.router.lifespan_context = lifespan


# ============================================================
#   FASTAPI ROUTES
# ============================================================

@app.post("/telegram")
async def telegram_webhook(request: Request):
    """Receives Telegram updates."""
    update = Update.de_json(await request.json(), app.state.tg_application.bot)
    await app.state.tg_application.process_update(update)
    return Response(status_code=200)


@app.get("/")
def root():
    return {"status": "running"}



# ============================================================
#   ADMIN PANEL PAGE
# ============================================================
@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    try:
        data = {
            "stages": fetch_all("SELECT id, name FROM stages ORDER BY id"),
            "terms": fetch_all("SELECT id, name, stage_id FROM terms ORDER BY id"),
            "grades": fetch_all("SELECT id, name, term_id FROM grades ORDER BY id"),
            "subjects": fetch_all("SELECT id, name, grade_id FROM subjects ORDER BY id"),
            "options": fetch_all("SELECT id, name FROM subject_options ORDER BY id"),
            "children": fetch_all("SELECT id, name, option_id FROM option_children ORDER BY id"),
            "subchildren": fetch_all("SELECT id, name, child_id FROM option_subchildren ORDER BY id"),
            "subjopt": fetch_all("SELECT subject_id, option_id FROM subject_option_map"),
            "resources": fetch_all("SELECT * FROM resources ORDER BY id DESC LIMIT 200"),
        }

        maps = {
            "stage_map": {s["id"]: s["name"] for s in data["stages"]},
            "term_map": {t["id"]: t["name"] for t in data["terms"]},
            "grade_map": {g["id"]: g["name"] for g in data["grades"]},
            "subject_map": {s["id"]: s["name"] for s in data["subjects"]},
            "option_map": {o["id"]: o["name"] for o in data["options"]},
            "child_map": {c["id"]: c["name"] for c in data["children"]},
            "sub_map": {sc["id"]: sc["name"] for sc in data["subchildren"]},
        }

        rows_html = ""
        for r in data["resources"]:
            rows_html += f"""
            <tr>
                <td>{r['id']}</td>
                <td>{maps['stage_map'].get(r['stage_id'], '')}</td>
                <td>{maps['term_map'].get(r['term_id'], '')}</td>
                <td>{maps['grade_map'].get(r['grade_id'], '')}</td>
                <td>{maps['subject_map'].get(r['subject_id'], '')}</td>
                <td>{maps['option_map'].get(r['option_id'], '')}</td>
                <td>{maps['child_map'].get(r['child_id'], '')}</td>
                <td>{maps['sub_map'].get(r['subchild_id'], '') if r['subchild_id'] else ''}</td>
                <td>{r['title']}</td>
                <td><a href="{r['url']}" target="_blank">فتح</a></td>

                <td><a class="btn btn-warning btn-sm" href="/admin/edit/{r['id']}">تعديل</a></td>

                <td>
                    <form method="post" action="/admin/delete/{r['id']}"
                          onsubmit="return confirm('❗ حذف نهائي؟');">
                        <input type="hidden" name="password" value="{ADMIN_PASSWORD}">
                        <button class="btn btn-danger btn-sm">🗑️</button>
                    </form>
                </td>
            </tr>
            """

        template_path = BASE_DIR / "admin_template.html"
        html = template_path.read_text(encoding="utf-8")

        html = html.replace("__ROWS__", rows_html)

        return HTMLResponse(html)

    except Exception as e:
        log.error(f"Admin panel error: {e}")
        return HTMLResponse("حدث خطأ في عرض لوحة التحكم.", status_code=500)



# ============================================================
#   ADD NEW RESOURCE
# ============================================================
@app.post("/admin/add")
async def admin_add(
    password: str = Form(...),
    stage_id: int = Form(...),
    term_id: int = Form(...),
    grade_id: int = Form(...),
    subject_id: int = Form(...),
    option_id: int = Form(...),
    child_id: int = Form(...),
    subchild_id: str = Form(""),
    title: str = Form(...),
    url: str = Form(""),
    file: UploadFile = File(None),
):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Incorrect password")

    if url and file and file.filename:
        raise HTTPException(status_code=400, detail="اختاري رابط أو PDF—not both")

    final_url = url.strip() or await save_uploaded_file(file)

    if not final_url:
        raise HTTPException(status_code=400, detail="يجب إدخال رابط أو رفع ملف")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO resources
                (title, url, stage_id, term_id, grade_id,
                 subject_id, option_id, child_id, subchild_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    final_url,
                    stage_id,
                    term_id,
                    grade_id,
                    subject_id,
                    option_id,
                    child_id,
                    int(subchild_id) if subchild_id else None,
                ),
            )
            conn.commit()
        return RedirectResponse("/admin", status_code=303)

    except Exception as e:
        log.error(f"Add error: {e}")
        raise HTTPException(status_code=500, detail="Database insert failed")



# ============================================================
#   EDIT PAGE
# ============================================================
@app.get("/admin/edit/{rid}", response_class=HTMLResponse)
def edit_page(rid: int):
    resource = fetch_one("SELECT * FROM resources WHERE id=?", (rid,))
    if not resource:
        return HTMLResponse("❌ الرابط غير موجود", status_code=404)

    return HTMLResponse(f"""
    <html dir="rtl">
    <head>
        <meta charset="utf-8">
        <title>تعديل البيانات</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
              rel="stylesheet">
    </head>
    <body class="p-4">
        <h3>✏️ تعديل الرابط رقم {rid}</h3>

        <form method="post" enctype="multipart/form-data">

            <label>العنوان:</label>
            <input name="title" class="form-control" value="{resource['title']}">

            <label class="mt-3">الرابط (اختياري):</label>
            <input name="url" class="form-control" value="{resource['url'] or ''}">

            <label class="mt-3">رفع PDF جديد (اختياري):</label>
            <input type="file" name="file" class="form-control" accept=".pdf">

            <button class="btn btn-success mt-4">حفظ</button>
        </form>

        <a href="/admin" class="btn btn-secondary mt-3">رجوع</a>
    </body>
    </html>
    """)



# ============================================================
#   EDIT SAVE
# ============================================================
@app.post("/admin/edit/{rid}")
async def edit_save(
    rid: int,
    title: str = Form(...),
    url: str = Form(""),
    file: UploadFile = File(None),
):

    final_url = url.strip()

    if file and file.filename:
        pdf_url = await save_uploaded_file(file)
        if pdf_url:
            final_url = pdf_url

    if not final_url:
        raise HTTPException(status_code=400, detail="يجب إدخال رابط أو رفع ملف")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE resources SET title=?, url=? WHERE id=?",
                (title, final_url, rid),
            )
            conn.commit()

        return RedirectResponse("/admin", status_code=303)

    except Exception as e:
        log.error(f"Edit error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update resource")



# ============================================================
#   DELETE
# ============================================================
@app.post("/admin/delete/{rid}")
def admin_delete(rid: int, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="❌ كلمة السر غلط")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM resources WHERE id=?", (rid,))
            conn.commit()

        return RedirectResponse("/admin", status_code=303)

    except Exception as e:
        log.error(f"Delete error: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete")

