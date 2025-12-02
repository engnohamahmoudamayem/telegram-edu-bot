# ============================================================
#   IMPORTS & CONFIG
# ============================================================
import os
import uuid
import json
import logging
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
#   LOAD ENV
# ============================================================
load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = BASE_DIR / "edu_bot_data.db"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

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
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("EDUBOT")

# ============================================================
#   DB CONNECTION
# ============================================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================
#   INIT DB (CREATE TABLES IF NOT EXISTS)
# ============================================================
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # stages
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )
    """)

    # terms
    cur.execute("""
    CREATE TABLE IF NOT EXISTS terms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        stage_id INTEGER NOT NULL
    )
    """)

    # grades
    cur.execute("""
    CREATE TABLE IF NOT EXISTS grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        term_id INTEGER NOT NULL
    )
    """)

    # subjects
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        grade_id INTEGER NOT NULL
    )
    """)

    # subject options
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subject_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    )
    """)

    # subject-option mapping
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subject_option_map (
        subject_id INTEGER NOT NULL,
        option_id INTEGER NOT NULL
    )
    """)

    # children
    cur.execute("""
    CREATE TABLE IF NOT EXISTS option_children (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        option_id INTEGER NOT NULL
    )
    """)

    # subchildren
    cur.execute("""
    CREATE TABLE IF NOT EXISTS option_subchildren (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        child_id INTEGER NOT NULL
    )
    """)

    # resources
    cur.execute("""
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
        subchild_id INTEGER
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ============================================================
#   SIMPLE DB HELPERS
# ============================================================
def fetch_all(query, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows

def fetch_one(query, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    conn.close()
    return row

async def save_uploaded_file(file: UploadFile):
    """Save uploaded PDF with unique name and return its public URL."""
    if not file or not file.filename:
        return None

    ext = Path(file.filename).suffix
    unique_name = f"{uuid.uuid4()}{ext}"
    save_path = UPLOAD_DIR / unique_name

    content = await file.read()
    save_path.write_bytes(content)

    log.info(f"Saved file: {unique_name}")
    return f"{APP_URL}/files/{unique_name}"

# ============================================================
#   BOT STATE
# ============================================================
user_state = {}

# ============================================================
#   KEYBOARD (RTL)
# ============================================================
def make_keyboard(options):
    rows = []
    for i in range(0, len(options), 2):
        row = [
            opt[0] if isinstance(opt, tuple) else opt
            for opt in options[i:i+2]
        ]
        row.reverse()  # RTL
        rows.append(row)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ============================================================
#   SEND RESOURCES
# ============================================================
async def send_resources(update: Update, state: dict):
    rows = fetch_all("""
        SELECT title, url FROM resources
        WHERE stage_id=? AND term_id=? AND grade_id=?
          AND subject_id=? AND option_id=? AND child_id=?
          AND (subchild_id = ? OR subchild_id IS NULL OR subchild_id = '')
    """, (
        state["stage_id"],
        state["term_id"],
        state["grade_id"],
        state["subject_id"],
        state["option_id"],
        state["child_id"],
        state.get("subchild_id")
    ))

    if not rows:
        return await update.message.reply_text("لا يوجد محتوى.")

    msg = "\n".join(f"▪️ <a href='{r['url']}'>{r['title']}</a>" for r in rows)
    await update.message.reply_text(
        msg, parse_mode="HTML", disable_web_page_preview=True
    )

# ============================================================
#   /START COMMAND
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat.id
    user_state[chat] = {"step": "stage"}

    stages = fetch_all("SELECT id, name FROM stages ORDER BY id")
    names = [(s["name"],) for s in stages]

    await update.message.reply_text(
        "✨ *منصة نيو أكاديمي التعليمية* ✨\nاختر المرحلة:",
        reply_markup=make_keyboard(names),
        parse_mode="Markdown"
    )

# ============================================================
#   MAIN BOT HANDLER
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat.id
    text = update.message.text.strip()

    if chat not in user_state:
        return await start(update, context)

    state = user_state[chat]

    # ---------------------- BACK BUTTON ----------------------
    if text == "رجوع ↩️":
        back = {
            "subchild": (
                "suboption",
                "SELECT name FROM option_children WHERE option_id=?",
                (state.get("option_id"),),
                "اختر القسم:"
            ),
            "suboption": (
                "option",
                """
                SELECT so.name FROM subject_option_map som
                JOIN subject_options so ON so.id = som.option_id
                WHERE som.subject_id=?
                """,
                (state.get("subject_id"),),
                "اختر نوع المحتوى:"
            ),
            "option": (
                "subject",
                "SELECT name FROM subjects WHERE grade_id=?",
                (state.get("grade_id"),),
                "اختر المادة:"
            ),
            "subject": (
                "grade",
                "SELECT name FROM grades WHERE term_id=?",
                (state.get("term_id"),),
                "اختر الصف:"
            ),
            "grade": (
                "term",
                "SELECT name FROM terms WHERE stage_id=?",
                (state.get("stage_id"),),
                "اختر الفصل:"
            ),
            "term": (
                "stage",
                "SELECT name FROM stages ORDER BY id",
                (),
                "اختر المرحلة:"
            ),
        }

        step = state.get("step")
        if step in back:
            new_step, query, params, msg = back[step]
            state["step"] = new_step
            options = fetch_all(query, params)
            return await update.message.reply_text(
                msg,
                reply_markup=make_keyboard([(o["name"],) for o in options])
            )

        return await start(update, context)

    # ---------------------- STAGE ----------------------
    if state["step"] == "stage":
        row = fetch_one("SELECT id FROM stages WHERE name=?", (text,))
        if not row:
            return
        state["stage_id"] = row["id"]
        state["step"] = "term"

        terms = fetch_all("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
        return await update.message.reply_text(
            "اختر الفصل:",
            reply_markup=make_keyboard([(t["name"],) for t in terms])
        )

    # ---------------------- TERM ----------------------
    if state["step"] == "term":
        row = fetch_one(
            "SELECT id FROM terms WHERE name=? AND stage_id=?",
            (text, state["stage_id"])
        )
        if not row:
            return
        state["term_id"] = row["id"]
        state["step"] = "grade"

        grades = fetch_all("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
        return await update.message.reply_text(
            "اختر الصف:",
            reply_markup=make_keyboard([(g["name"],) for g in grades])
        )

    # ---------------------- GRADE ----------------------
    if state["step"] == "grade":
        row = fetch_one("SELECT id FROM grades WHERE name=?", (text,))
        if not row:
            return
        state["grade_id"] = row["id"]
        state["step"] = "subject"

        subjects = fetch_all("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
        return await update.message.reply_text(
            "اختر المادة:",
            reply_markup=make_keyboard([(s["name"],) for s in subjects])
        )

    # ---------------------- SUBJECT ----------------------
    if state["step"] == "subject":
        row = fetch_one("SELECT id FROM subjects WHERE name=?", (text,))
        if not row:
            return
        state["subject_id"] = row["id"]
        state["step"] = "option"

        options = fetch_all("""
            SELECT so.name
            FROM subject_option_map som
            JOIN subject_options so ON so.id = som.option_id
            WHERE som.subject_id=?
        """, (state["subject_id"],))

        return await update.message.reply_text(
            "اختر نوع المحتوى:",
            reply_markup=make_keyboard([(o["name"],) for o in options])
        )

    # ---------------------- OPTION ----------------------
    if state["step"] == "option":
        row = fetch_one("SELECT id FROM subject_options WHERE name=?", (text,))
        if not row:
            return
        state["option_id"] = row["id"]
        state["step"] = "suboption"

        children = fetch_all(
            "SELECT name FROM option_children WHERE option_id=?",
            (state["option_id"],)
        )
        return await update.message.reply_text(
            "اختر القسم:",
            reply_markup=make_keyboard([(c["name"],) for c in children])
        )

    # ---------------------- SUBOPTION (child) ----------------------
    if state["step"] == "suboption":
        row = fetch_one(
            "SELECT id FROM option_children WHERE name=? AND option_id=?",
            (text, state["option_id"])
        )
        if not row:
            return

        state["child_id"] = row["id"]

        subs = fetch_all(
            "SELECT name FROM option_subchildren WHERE child_id=?",
            (state["child_id"],)
        )

        if subs:
            state["step"] = "subchild"
            return await update.message.reply_text(
                "اختر القسم الفرعي:",
                reply_markup=make_keyboard([(s["name"],) for s in subs])
            )

        return await send_resources(update, state)

    # ---------------------- SUBCHILD ----------------------
    if state["step"] == "subchild":
        row = fetch_one(
            "SELECT id FROM option_subchildren WHERE name=? AND child_id=?",
            (text, state["child_id"])
        )
        if not row:
            return

        state["subchild_id"] = row["id"]
        return await send_resources(update, state)
# ============================================================
#   FASTAPI APP + TELEGRAM WEBHOOK
# ============================================================
app = FastAPI(title="Edu Bot API")

# خدمة ملفات الـ PDF المرفوعة
app.mount("/files", StaticFiles(directory=str(UPLOAD_DIR)), name="files")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """تشغيل بوت تيليجرام مع FastAPI (startup/shutdown)."""
    log.info("Starting Telegram application...")
    tg_app = Application.builder().token(BOT_TOKEN).build()

    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # set webhook
    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")
    app.state.tg_application = tg_app

    async with tg_app:
        await tg_app.start()
        yield
        await tg_app.stop()

    log.info("Telegram application stopped.")

app.router.lifespan_context = lifespan


@app.post("/telegram")
async def telegram_webhook(request: Request):
    """استقبال التحديثات من تيليجرام."""
    update = Update.de_json(await request.json(), app.state.tg_application.bot)
    await app.state.tg_application.process_update(update)
    return Response(status_code=200)


@app.get("/")
def root():
    return {"status": "running"}
# ============================================================
#   ADMIN PANEL HELPER
# ============================================================
def build_resources_rows():
    """يبني صفوف جدول الموارد في لوحة التحكم."""
    stages = fetch_all("SELECT id, name FROM stages ORDER BY id")
    terms = fetch_all("SELECT id, name, stage_id FROM terms ORDER BY id")
    grades = fetch_all("SELECT id, name, term_id FROM grades ORDER BY id")
    subjects = fetch_all("SELECT id, name, grade_id FROM subjects ORDER BY id")
    options = fetch_all("SELECT id, name FROM subject_options ORDER BY id")
    children = fetch_all("SELECT id, name, option_id FROM option_children ORDER BY id")
    subchildren = fetch_all("SELECT id, name, child_id FROM option_subchildren ORDER BY id")
    subjopt = fetch_all("SELECT subject_id, option_id FROM subject_option_map")

    resources = fetch_all(
        """
        SELECT id, title, url,
               stage_id, term_id, grade_id,
               subject_id, option_id, child_id, subchild_id
        FROM resources
        ORDER BY id DESC
        LIMIT 200
        """
    )

    # خرائط أسماء
    stage_map = {s["id"]: s["name"] for s in stages}
    term_map = {t["id"]: t["name"] for t in terms}
    grade_map = {g["id"]: g["name"] for g in grades}
    subject_map = {s["id"]: s["name"] for s in subjects}
    option_map = {o["id"]: o["name"] for o in options}
    child_map = {c["id"]: c["name"] for c in children}
    sub_map = {sc["id"]: sc["name"] for sc in subchildren}

    rows_html = ""
    for r in resources:
        rows_html += f"""
        <tr>
            <td>{r['id']}</td>
            <td>{stage_map.get(r['stage_id'], '')}</td>
            <td>{term_map.get(r['term_id'], '')}</td>
            <td>{grade_map.get(r['grade_id'], '')}</td>
            <td>{subject_map.get(r['subject_id'], '')}</td>
            <td>{option_map.get(r['option_id'], '')}</td>
            <td>{child_map.get(r['child_id'], '')}</td>
            <td>{sub_map.get(r['subchild_id'], '') if r['subchild_id'] else ''}</td>
            <td>{r['title']}</td>
            <td><a href="{r['url']}" target="_blank">فتح</a></td>
            <td><a class="btn btn-warning btn-sm" href="/admin/edit/{r['id']}">تعديل</a></td>
            <td>
                <form method="post" action="/admin/delete/{r['id']}"
                      onsubmit="return confirm('حذف نهائي؟');">
                    <input type="password" name="password" placeholder="كلمة السر" class="form-control form-control-sm mb-1" required>
                    <button class="btn btn-danger btn-sm">🗑️</button>
                </form>
            </td>
        </tr>
        """

    return {
        "stages": stages,
        "terms": terms,
        "grades": grades,
        "subjects": subjects,
        "options": options,
        "children": children,
        "subchildren": subchildren,
        "subjopt": subjopt,
        "rows_html": rows_html,
    }

# ============================================================
#   ADMIN PAGE
# ============================================================
@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    """عرض صفحة لوحة التحكم."""
    data = build_resources_rows()

    template_path = BASE_DIR / "admin_template.html"
    if not template_path.exists():
        raise HTTPException(status_code=500, detail="admin_template.html غير موجود في نفس المجلد.")

    html = template_path.read_text(encoding="utf-8")

    # حقن الصفوف
    html = html.replace("__ROWS__", data["rows_html"])

    # حقن بيانات الـ JSON داخل سكربتات الـ HTML
    html = html.replace("__STAGES__", json.dumps([dict(r) for r in data["stages"]], ensure_ascii=False))
    html = html.replace("__TERMS__", json.dumps([dict(r) for r in data["terms"]], ensure_ascii=False))
    html = html.replace("__GRADES__", json.dumps([dict(r) for r in data["grades"]], ensure_ascii=False))
    html = html.replace("__SUBJECTS__", json.dumps([dict(r) for r in data["subjects"]], ensure_ascii=False))
    html = html.replace("__OPTIONS__", json.dumps([dict(r) for r in data["options"]], ensure_ascii=False))
    html = html.replace("__CHILDREN__", json.dumps([dict(r) for r in data["children"]], ensure_ascii=False))
    html = html.replace("__SUBCHILDREN__", json.dumps([dict(r) for r in data["subchildren"]], ensure_ascii=False))
    html = html.replace("__SUBJOPT__", json.dumps([dict(r) for r in data["subjopt"]], ensure_ascii=False))

    return HTMLResponse(html)

# ============================================================
#   ADMIN: ADD NEW RESOURCE
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
        raise HTTPException(status_code=401, detail="كلمة المرور غير صحيحة")

    # لا يسمح برابط + ملف في نفس الوقت
    if url.strip() and file and file.filename:
        raise HTTPException(status_code=400, detail="اختاري رابط *أو* PDF فقط، وليس الاثنين معًا.")

    final_url = url.strip()

    if file and file.filename:
        file_url = await save_uploaded_file(file)
        if not file_url:
            raise HTTPException(status_code=500, detail="فشل في حفظ الملف.")
        final_url = file_url

    if not final_url:
        raise HTTPException(status_code=400, detail="يجب إدخال رابط أو رفع ملف PDF.")

    sub_val = int(subchild_id) if subchild_id.strip() else None

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO resources (
                title, url,
                stage_id, term_id, grade_id,
                subject_id, option_id, child_id, subchild_id
            )
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
                sub_val,
            ),
        )
        conn.commit()
        conn.close()
        log.info(f"Added resource: {title}")
        return RedirectResponse("/admin", status_code=303)
    except Exception as e:
        log.error(f"Error inserting resource: {e}")
        raise HTTPException(status_code=500, detail="فشل في حفظ البيانات في قاعدة البيانات.")

# ============================================================
#   ADMIN: EDIT PAGE
# ============================================================
@app.get("/admin/edit/{rid}", response_class=HTMLResponse)
def edit_page(rid: int):
    resource = fetch_one("SELECT * FROM resources WHERE id=?", (rid,))
    if not resource:
        raise HTTPException(status_code=404, detail="المورد غير موجود.")

    return HTMLResponse(f"""
    <html dir="rtl">
    <head>
        <meta charset="utf-8">
        <title>تعديل البيانات</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>

    <body class="p-4">
        <h3 class="mb-3">✏️ تعديل الرابط رقم {rid}</h3>

        <form method="post" enctype="multipart/form-data">
            <label class="mt-2">العنوان:</label>
            <input name="title" class="form-control" value="{resource['title']}">

            <label class="mt-3">الرابط (إن وجد):</label>
            <input name="url" class="form-control" value="{resource['url'] or ''}">

            <label class="mt-3">رفع PDF جديد (اختياري):</label>
            <input type="file" name="file" class="form-control" accept=".pdf">

            <button class="btn btn-success mt-4">💾 حفظ التعديلات</button>
        </form>

        <a href="/admin" class="btn btn-secondary mt-3">⬅️ رجوع للوحة التحكم</a>
    </body>
    </html>
    """)

# ============================================================
#   ADMIN: SAVE EDIT
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
        file_url = await save_uploaded_file(file)
        if file_url:
            final_url = file_url

    if not final_url:
        raise HTTPException(status_code=400, detail="يجب إدخال رابط أو رفع ملف.")

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE resources SET title=?, url=? WHERE id=?",
            (title, final_url, rid),
        )
        conn.commit()
        conn.close()
        log.info(f"Resource {rid} updated.")
        return RedirectResponse("/admin", status_code=303)
    except Exception as e:
        log.error(f"Error updating resource: {e}")
        raise HTTPException(status_code=500, detail="فشل في تحديث البيانات.")

# ============================================================
#   ADMIN: DELETE
# ============================================================
@app.post("/admin/delete/{rid}")
def admin_delete(rid: int, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="كلمة المرور غير صحيحة")

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM resources WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        log.info(f"Resource {rid} deleted.")
        return RedirectResponse("/admin", status_code=303)
    except Exception as e:
        log.error(f"Error deleting resource: {e}")
        raise HTTPException(status_code=500, detail="فشل في حذف البيانات.")
