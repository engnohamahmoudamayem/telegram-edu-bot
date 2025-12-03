# ============================================================
#   IMPORTS & CONFIG
# ============================================================
import os
import uuid
import json
import logging
from pathlib import Path
from contextlib import asynccontextmanager
import asyncio

import psycopg2
import psycopg2.extras

from fastapi import (
    FastAPI,
    Request,
    Response,
    Form,
    UploadFile,
    File,
    HTTPException,
)
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
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DATABASE_URL = os.environ.get("DATABASE_URL")

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL missing for PostgreSQL!")

safe_db = DATABASE_URL.split("@")[-1]
print("📌 USING DATABASE_URL =", safe_db)

# ============================================================
#   LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("EDU_BOT")

# ============================================================
#   POSTGRESQL CONNECTION
# ============================================================
try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    log.info("✅ Connected to PostgreSQL successfully!")
except Exception as e:
    raise RuntimeError(f"❌ Cannot connect to PostgreSQL: {e}")


def db_fetch_all(query: str, params=()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def db_fetch_one(query: str, params=()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchone()


def db_execute(query: str, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)


# ============================================================
#   INIT DB
# ============================================================
def init_db_pg():
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS stages (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE);""")

        cur.execute("""CREATE TABLE IF NOT EXISTS terms (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL, stage_id INTEGER REFERENCES stages(id));""")

        cur.execute("""CREATE TABLE IF NOT EXISTS grades (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL, term_id INTEGER REFERENCES terms(id));""")

        cur.execute("""CREATE TABLE IF NOT EXISTS subjects (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL, grade_id INTEGER REFERENCES grades(id));""")

        cur.execute("""CREATE TABLE IF NOT EXISTS subject_options (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL);""")

        cur.execute("""CREATE TABLE IF NOT EXISTS subject_option_map (
            subject_id INTEGER REFERENCES subjects(id),
            option_id INTEGER REFERENCES subject_options(id));""")

        cur.execute("""CREATE TABLE IF NOT EXISTS option_children (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL, option_id INTEGER REFERENCES subject_options(id));""")

        cur.execute("""CREATE TABLE IF NOT EXISTS option_subchildren (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL, child_id INTEGER REFERENCES option_children(id));""")

        cur.execute("""CREATE TABLE IF NOT EXISTS resources (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER REFERENCES subjects(id),
            option_id INTEGER REFERENCES subject_options(id),
            child_id INTEGER REFERENCES option_children(id),
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            subchild_id INTEGER REFERENCES option_subchildren(id),
            stage_id INTEGER REFERENCES stages(id),
            term_id INTEGER REFERENCES terms(id),
            grade_id INTEGER REFERENCES grades(id));""")

    log.info("✅ PostgreSQL tables ensured.")


init_db_pg()

# ============================================================
#   UTILS: SAVE FILE
# ============================================================
async def save_uploaded_file(file: UploadFile) -> str | None:
    if not file or not file.filename:
        return None

    ext = Path(file.filename).suffix or ".pdf"
    unique_name = f"{uuid.uuid4()}{ext}"
    save_path = UPLOAD_DIR / unique_name

    save_path.write_bytes(await file.read())

    return f"{APP_URL}/files/{unique_name}"


# ============================================================
#   BOT STATE
# ============================================================
user_state: dict[int, dict] = {}

# ============================================================
#   KEYBOARD (RTL)
# ============================================================
def make_keyboard(options):
    labels = [str(o).strip() for o in options if str(o).strip()]
    rows = []
    for i in range(0, len(labels), 2):
        row = labels[i:i+2][::-1]
        rows.append(row)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ============================================================
#   SEND RESOURCES
# ============================================================
async def send_resources(update: Update, state: dict):
    resources = db_fetch_all(
        """SELECT title, url FROM resources
           WHERE stage_id=%s AND term_id=%s AND grade_id=%s
           AND subject_id=%s AND option_id=%s AND child_id=%s
           AND (subchild_id=%s OR (subchild_id IS NULL AND %s IS NULL))""",
        (
            state["stage_id"], state["term_id"], state["grade_id"],
            state["subject_id"], state["option_id"], state["child_id"],
            state.get("subchild_id"), state.get("subchild_id")
        )
    )

    if not resources:
        return await update.message.reply_text("لا يوجد محتوى.")

    msg = "\n".join(f"▪️ <a href='{r['url']}'>{r['title']}</a>" for r in resources)
    await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)


# ============================================================
#   /START COMMAND
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    stages = db_fetch_all("SELECT name FROM stages ORDER BY id")
    names = [s["name"] for s in stages]

    text = "✨ *منصة نيو أكاديمي التعليمية* ✨\nاختر المرحلة:"
    await update.message.reply_text(text, reply_markup=make_keyboard(names), parse_mode="Markdown")
# ============================================================
#   MAIN TELEGRAM HANDLER
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]
    step = state.get("step")
    log.info(f"📩 USER CLICKED: {text} | STEP = {step}")

    # ========================================================
    #   BACK BUTTON
    # ========================================================
    if text == "رجوع ↩️":
        back_flow = {
            "subchild": ("suboption",
                         "SELECT name FROM option_children WHERE option_id=%s",
                         (state.get("option_id"),),
                         "اختر القسم:"),
            "suboption": ("option",
                          """SELECT so.name FROM subject_option_map som
                             JOIN subject_options so ON so.id = som.option_id
                             WHERE som.subject_id=%s""",
                          (state.get("subject_id"),),
                          "اختر نوع المحتوى:"),
            "option": ("subject",
                       "SELECT name FROM subjects WHERE grade_id=%s",
                       (state.get("grade_id"),),
                       "اختر المادة:"),
            "subject": ("grade",
                        "SELECT name FROM grades WHERE term_id=%s",
                        (state.get("term_id"),),
                        "اختر الصف:"),
            "grade": ("term",
                      "SELECT name FROM terms WHERE stage_id=%s",
                      (state.get("stage_id"),),
                      "اختر الفصل:"),
            "term": ("stage",
                     "SELECT name FROM stages ORDER BY id",
                     (),
                     "اختر المرحلة:"),
        }

        if step in back_flow:
            new_step, query, params, msg = back_flow[step]
            state["step"] = new_step
            rows = db_fetch_all(query, params)
            names = [r["name"] for r in rows]
            return await update.message.reply_text(msg, reply_markup=make_keyboard(names))

        return await start(update, context)

    # ========================================================
    #   STAGE
    # ========================================================
    if step == "stage":
        row = db_fetch_one("SELECT id FROM stages WHERE name=%s", (text,))
        if not row:
            return
        state["stage_id"] = row["id"]
        state["step"] = "term"

        terms = db_fetch_all(
            "SELECT name FROM terms WHERE stage_id=%s", (state["stage_id"],)
        )
        names = [t["name"] for t in terms]
        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(names))

    # ========================================================
    #   TERM
    # ========================================================
    if step == "term":
        row = db_fetch_one(
            "SELECT id FROM terms WHERE name=%s AND stage_id=%s",
            (text, state["stage_id"])
        )
        if not row:
            return
        state["term_id"] = row["id"]
        state["step"] = "grade"

        grades = db_fetch_all("SELECT name FROM grades WHERE term_id=%s", (state["term_id"],))
        names = [g["name"] for g in grades]
        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(names))

    # ========================================================
    #   GRADE
    # ========================================================
    if step == "grade":
        row = db_fetch_one(
            "SELECT id FROM grades WHERE name=%s AND term_id=%s",
            (text, state["term_id"])
        )
        if not row:
            return
        state["grade_id"] = row["id"]
        state["step"] = "subject"

        subjects = db_fetch_all("SELECT name FROM subjects WHERE grade_id=%s", (state["grade_id"],))
        names = [s["name"] for s in subjects]
        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(names))

    # ========================================================
    #   SUBJECT
    # ========================================================
    if step == "subject":
        row = db_fetch_one(
            "SELECT id FROM subjects WHERE name=%s AND grade_id=%s",
            (text, state["grade_id"])
        )
        if not row:
            return
        state["subject_id"] = row["id"]
        state["step"] = "option"

        opts = db_fetch_all(
            """SELECT so.name FROM subject_option_map som
               JOIN subject_options so ON so.id = som.option_id
               WHERE som.subject_id=%s""",
            (state["subject_id"],)
        )
        names = [o["name"] for o in opts]
        return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(names))

    # ========================================================
    #   OPTION
    # ========================================================
    if step == "option":
        row = db_fetch_one("SELECT id FROM subject_options WHERE name=%s", (text,))
        if not row:
            return
        state["option_id"] = row["id"]
        state["step"] = "suboption"

        children = db_fetch_all(
            "SELECT name FROM option_children WHERE option_id=%s",
            (state["option_id"],)
        )
        names = [c["name"] for c in children]
        return await update.message.reply_text("اختر القسم:", reply_markup=make_keyboard(names))

    # ========================================================
    #   SUBOPTION
    # ========================================================
    if step == "suboption":
        row = db_fetch_one(
            "SELECT id FROM option_children WHERE name=%s AND option_id=%s",
            (text, state["option_id"])
        )
        if not row:
            return
        state["child_id"] = row["id"]

        subs = db_fetch_all(
            "SELECT name FROM option_subchildren WHERE child_id=%s",
            (state["child_id"],)
        )

        if subs:
            state["step"] = "subchild"
            names = [s["name"] for s in subs]
            return await update.message.reply_text(
                "اختر القسم الفرعي:", reply_markup=make_keyboard(names)
            )

        return await send_resources(update, state)

    # ========================================================
    #   SUBCHILD
    # ========================================================
    if step == "subchild":
        row = db_fetch_one(
            "SELECT id FROM option_subchildren WHERE name=%s AND child_id=%s",
            (text, state["child_id"])
        )
        if not row:
            return

        state["subchild_id"] = row["id"]
        return await send_resources(update, state)
# ============================================================
#   TELEGRAM BOT INITIALIZATION
# ============================================================
import asyncio

app = FastAPI(title="Edu Bot API")
app.mount("/files", StaticFiles(directory=str(UPLOAD_DIR)), name="files")

# Telegram application (ONE instance)
tg_app = Application.builder().token(BOT_TOKEN).build()

# Register handlers
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


async def start_bot():
    """Initialize Telegram bot on startup."""
    log.info("🚀 Starting Telegram Bot...")

    await tg_app.initialize()
    await tg_app.start()

    # Set webhook
    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")

    log.info("✅ Webhook set & bot running!")


# Start bot background task
asyncio.get_event_loop().create_task(start_bot())


# ============================================================
#   TELEGRAM WEBHOOK ENDPOINT
# ============================================================
@app.post("/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, tg_app.bot)

        await tg_app.process_update(update)

    except Exception as e:
        log.error(f"❌ Webhook Error: {e}")

    return Response(status_code=200)


# ============================================================
#   ADMIN PANEL HELPERS
# ============================================================
def build_resources_context():
    stages = db_fetch_all("SELECT id, name FROM stages ORDER BY id")
    terms = db_fetch_all("SELECT id, name, stage_id FROM terms ORDER BY id")
    grades = db_fetch_all("SELECT id, name, term_id FROM grades ORDER BY id")
    subjects = db_fetch_all("SELECT id, name, grade_id FROM subjects ORDER BY id")
    options = db_fetch_all("SELECT id, name FROM subject_options ORDER BY id")
    children = db_fetch_all(
        "SELECT id, name, option_id FROM option_children ORDER BY id"
    )
    subchildren = db_fetch_all(
        "SELECT id, name, child_id FROM option_subchildren ORDER BY id"
    )
    subjopt = db_fetch_all("SELECT subject_id, option_id FROM subject_option_map")

    resources = db_fetch_all(
        """
        SELECT id, title, url, stage_id, term_id, grade_id,
               subject_id, option_id, child_id, subchild_id
        FROM resources ORDER BY id DESC LIMIT 200
        """
    )

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
                      onsubmit="return confirm('هل تريد الحذف؟');">
                    <input type="password" name="password" placeholder="كلمة السر"
                           class="form-control form-control-sm mb-1" required>
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
    data = build_resources_context()

    template_path = BASE_DIR / "admin_template.html"
    if not template_path.exists():
        raise HTTPException(status_code=500, detail="الملف admin_template.html غير موجود")

    html = template_path.read_text(encoding="utf-8")

    html = html.replace("__ROWS__", data["rows_html"])
    html = html.replace("__STAGES__", json.dumps(data["stages"], ensure_ascii=False))
    html = html.replace("__TERMS__", json.dumps(data["terms"], ensure_ascii=False))
    html = html.replace("__GRADES__", json.dumps(data["grades"], ensure_ascii=False))
    html = html.replace("__SUBJECTS__", json.dumps(data["subjects"], ensure_ascii=False))
    html = html.replace("__OPTIONS__", json.dumps(data["options"], ensure_ascii=False))
    html = html.replace("__CHILDREN__", json.dumps(data["children"], ensure_ascii=False))
    html = html.replace("__SUBCHILDREN__", json.dumps(data["subchildren"], ensure_ascii=False))
    html = html.replace("__SUBJOPT__", json.dumps(data["subjopt"], ensure_ascii=False))

    return HTMLResponse(html)


# ============================================================
#   ADD RESOURCE
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
    file: UploadFile | None = File(None),
):
    if password != ADMIN_PASSWORD:
        raise HTTPException(401, "خطأ في كلمة المرور")

    if url.strip() and file and file.filename:
        raise HTTPException(400, "اختاري رابط أو PDF فقط")

    final_url = url.strip()

    if file and file.filename:
        file_url = await save_uploaded_file(file)
        final_url = file_url

    if not final_url:
        raise HTTPException(400, "يجب إدخال رابط أو ملف")

    sub_val = int(subchild_id) if subchild_id.strip() else None

    db_execute(
        """
        INSERT INTO resources (
            subject_id, option_id, child_id,
            title, url, subchild_id,
            stage_id, term_id, grade_id
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (subject_id, option_id, child_id, title, final_url,
         sub_val, stage_id, term_id, grade_id),
    )

    return RedirectResponse("/admin", 303)


# ============================================================
#   EDIT PAGE
# ============================================================
@app.get("/admin/edit/{rid}", response_class=HTMLResponse)
def admin_edit_page(rid: int):
    r = db_fetch_one("SELECT * FROM resources WHERE id=%s", (rid,))
    if not r:
        raise HTTPException(404, "غير موجود")

    return HTMLResponse(f"""
        <html dir="rtl">
        <body class="p-4">
            <h3>تعديل العنصر رقم {r['id']}</h3>

            <form method="post" enctype="multipart/form-data">
                <label>العنوان:</label>
                <input name="title" class="form-control" value="{r['title']}">

                <label class="mt-3">الرابط:</label>
                <input name="url" class="form-control" value="{r['url']}">

                <label class="mt-3">رفع PDF جديد:</label>
                <input type="file" name="file" class="form-control">

                <button class="btn btn-success mt-4">حفظ</button>
            </form>

            <a href="/admin" class="btn btn-secondary mt-3">عودة</a>
        </body>
        </html>
    """)


# ============================================================
#   SAVE EDIT
# ============================================================
@app.post("/admin/edit/{rid}")
async def admin_edit_save(
    rid: int,
    title: str = Form(...),
    url: str = Form(""),
    file: UploadFile | None = File(None),
):
    final_url = url.strip()

    if file and file.filename:
        file_url = await save_uploaded_file(file)
        final_url = file_url

    db_execute(
        "UPDATE resources SET title=%s, url=%s WHERE id=%s",
        (title, final_url, rid)
    )

    return RedirectResponse("/admin", 303)


# ============================================================
#   DELETE RESOURCE
# ============================================================
@app.post("/admin/delete/{rid}")
def admin_delete(rid: int, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(401, "كلمة المرور غير صحيحة")

    db_execute("DELETE FROM resources WHERE id=%s", (rid,))

    return RedirectResponse("/admin", 303)
