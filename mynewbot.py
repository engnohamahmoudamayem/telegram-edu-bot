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

from fastapi import (
    FastAPI, Request, Response, Form, UploadFile, File,
    HTTPException, Cookie
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import psycopg2
import psycopg2.extras

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Fix event loop for Render
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

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
print("🔐 ADMIN_PASSWORD currently in use →", ADMIN_PASSWORD)

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("BOT_TOKEN أو APP_URL مفقود!")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL مفقود!")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("EDU_BOT")

# ============================================================
#   CONNECT TO POSTGRES
# ============================================================
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True

def db_fetch_all(q, p=()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(q, p)
        return cur.fetchall()

def db_fetch_one(q, p=()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(q, p)
        return cur.fetchone()

def db_execute(q, p=()):
    with conn.cursor() as cur:
        cur.execute(q, p)

# ============================================================
#   INIT DATABASE
# ============================================================
def init_db():
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS stages (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE );""")

    cur.execute("""CREATE TABLE IF NOT EXISTS terms (
        id SERIAL PRIMARY KEY,
        name TEXT,
        stage_id INTEGER REFERENCES stages(id) );""")

    cur.execute("""CREATE TABLE IF NOT EXISTS grades (
        id SERIAL PRIMARY KEY,
        name TEXT,
        term_id INTEGER REFERENCES terms(id) );""")

    cur.execute("""CREATE TABLE IF NOT EXISTS subjects (
        id SERIAL PRIMARY KEY,
        name TEXT,
        grade_id INTEGER REFERENCES grades(id) );""")

    cur.execute("""CREATE TABLE IF NOT EXISTS subject_options (
        id SERIAL PRIMARY KEY,
        name TEXT );""")

    cur.execute("""CREATE TABLE IF NOT EXISTS subject_option_map (
        subject_id INTEGER REFERENCES subjects(id),
        option_id INTEGER REFERENCES subject_options(id) );""")

    cur.execute("""CREATE TABLE IF NOT EXISTS option_children (
        id SERIAL PRIMARY KEY,
        name TEXT,
        option_id INTEGER REFERENCES subject_options(id) );""")

    cur.execute("""CREATE TABLE IF NOT EXISTS option_subchildren (
        id SERIAL PRIMARY KEY,
        name TEXT,
        child_id INTEGER REFERENCES option_children(id) );""")

    cur.execute("""CREATE TABLE IF NOT EXISTS resources (
        id SERIAL PRIMARY KEY,
        subject_id INTEGER REFERENCES subjects(id),
        option_id INTEGER REFERENCES subject_options(id),
        child_id INTEGER REFERENCES option_children(id),
        subchild_id INTEGER REFERENCES option_subchildren(id),
        stage_id INTEGER REFERENCES stages(id),
        term_id INTEGER REFERENCES terms(id),
        grade_id INTEGER REFERENCES grades(id),
        title TEXT NOT NULL,
        url TEXT NOT NULL );""")

    cur.close()
    log.info("✅ Database ready!")

init_db()

# ============================================================
#   FILE UPLOAD
# ============================================================
async def save_uploaded_file(file: UploadFile):
    if not file or not file.filename:
        return None

    ext = Path(file.filename).suffix or ".pdf"
    name = f"{uuid.uuid4()}{ext}"
    path = UPLOAD_DIR / name
    path.write_bytes(await file.read())
    return f"{APP_URL}/files/{name}"

# ============================================================
#   BOT STATE + KEYBOARD
# ============================================================
user_state = {}

def make_keyboard(opts):
    labels = [o for o in opts if o]
    rows = []
    for i in range(0, len(labels), 2):
        r = labels[i:i+2]
        r.reverse()
        rows.append(r)

    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ============================================================
#   SEND RESOURCES
# ============================================================
async def send_resources(update: Update, st: dict):
    rows = db_fetch_all("""
        SELECT title, url FROM resources
        WHERE stage_id=%s AND term_id=%s AND grade_id=%s
        AND subject_id=%s AND option_id=%s AND child_id=%s
        AND (subchild_id=%s OR subchild_id IS NULL)
    """, (
        st["stage_id"], st["term_id"], st["grade_id"],
        st["subject_id"], st["option_id"], st["child_id"],
        st.get("subchild_id"),
    ))

    if not rows:
        return await update.message.reply_text("لا يوجد محتوى.")

    msg = "\n".join(f"▪ <a href='{r['url']}'>{r['title']}</a>" for r in rows)
    await update.message.reply_text(msg, parse_mode="HTML")
# ============================================================
#   START COMMAND
# ============================================================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    user_state[cid] = {"step": "stage", "history": []}

    rows = db_fetch_all("SELECT name FROM stages ORDER BY id")
    names = [r["name"] for r in rows]

    await update.message.reply_text(
        "✨ *منصة نيو أكاديمي التعليمية* ✨\nاختر المرحلة:",
        reply_markup=make_keyboard(names),
        parse_mode="Markdown",
    )

# ============================================================
#   MAIN MESSAGE HANDLER
# ============================================================
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    text = (update.message.text or "").strip()

    if cid not in user_state:
        return await start(update, ctx)

    st = user_state[cid]
    step = st["step"]

    # ========================================================
    #   BACK BUTTON
    # ========================================================
    if text == "رجوع ↩️":
        if not st["history"]:
            return await start(update, ctx)

        previous_step = st["history"].pop()
        st["step"] = previous_step

        # STAGE
        if previous_step == "stage":
            rows = db_fetch_all("SELECT name FROM stages ORDER BY id")
            return await update.message.reply_text(
                "اختر المرحلة:",
                reply_markup=make_keyboard([r["name"] for r in rows]),
            )

        # TERM
        if previous_step == "term":
            st.pop("grade_id", None)
            st.pop("subject_id", None)
            rows = db_fetch_all(
                "SELECT name FROM terms WHERE stage_id=%s",
                (st["stage_id"],),
            )
            return await update.message.reply_text(
                "اختر الفصل الدراسي:",
                reply_markup=make_keyboard([r["name"] for r in rows]),
            )

        # GRADE
        if previous_step == "grade":
            st.pop("subject_id", None)
            rows = db_fetch_all(
                "SELECT name FROM grades WHERE term_id=%s",
                (st["term_id"],),
            )
            return await update.message.reply_text(
                "اختر الصف الدراسي:",
                reply_markup=make_keyboard([r["name"] for r in rows]),
            )

        # SUBJECT
        if previous_step == "subject":
            st.pop("option_id", None)
            rows = db_fetch_all(
                "SELECT name FROM subjects WHERE grade_id=%s",
                (st["grade_id"],),
            )
            return await update.message.reply_text(
                "اختر المادة:",
                reply_markup=make_keyboard([r["name"] for r in rows]),
            )

        # OPTION
        if previous_step == "option":
            st.pop("child_id", None)
            rows = db_fetch_all("""
                SELECT so.name FROM subject_options so
                JOIN subject_option_map som ON so.id = som.option_id
                WHERE som.subject_id=%s
            """, (st["subject_id"],))
            return await update.message.reply_text(
                "اختر نوع المحتوى:",
                reply_markup=make_keyboard([r["name"] for r in rows]),
            )

        # CHILD
        if previous_step == "child_option":
            st.pop("subchild_id", None)
            rows = db_fetch_all(
                "SELECT name FROM option_children WHERE option_id=%s",
                (st["option_id"],),
            )
            return await update.message.reply_text(
                "اختر الفصل أو الوحدة:",
                reply_markup=make_keyboard([r["name"] for r in rows]),
            )

    # ========================================================
    #   NORMAL FLOW (STAGE → TERM → GRADE → SUBJECT ...)
    # ========================================================

    # STAGE
    if step == "stage":
        row = db_fetch_one("SELECT id FROM stages WHERE name=%s", (text,))
        if not row:
            return await update.message.reply_text("هذه المرحلة غير صحيحة.")

        st["stage_id"] = row["id"]
        st["history"].append("stage")
        st["step"] = "term"

        rows = db_fetch_all(
            "SELECT name FROM terms WHERE stage_id=%s", (row["id"],)
        )
        return await update.message.reply_text(
            "اختر الفصل الدراسي:",
            reply_markup=make_keyboard([r["name"] for r in rows]),
        )

    # TERM
    if step == "term":
        row = db_fetch_one(
            "SELECT id FROM terms WHERE stage_id=%s AND name=%s",
            (st["stage_id"], text),
        )
        if not row:
            return await update.message.reply_text("هذا الفصل غير صحيح.")

        st["term_id"] = row["id"]
        st["history"].append("term")
        st["step"] = "grade"

        rows = db_fetch_all(
            "SELECT name FROM grades WHERE term_id=%s", (row["id"],)
        )
        return await update.message.reply_text(
            "اختر الصف الدراسي:",
            reply_markup=make_keyboard([r["name"] for r in rows]),
        )

    # GRADE
    if step == "grade":
        row = db_fetch_one(
            "SELECT id FROM grades WHERE term_id=%s AND name=%s",
            (st["term_id"], text),
        )
        if not row:
            return await update.message.reply_text("هذا الصف غير صحيح.")

        st["grade_id"] = row["id"]
        st["history"].append("grade")
        st["step"] = "subject"

        rows = db_fetch_all(
            "SELECT name FROM subjects WHERE grade_id=%s", (row["id"],)
        )
        return await update.message.reply_text(
            "اختر المادة:",
            reply_markup=make_keyboard([r["name"] for r in rows]),
        )

    # SUBJECT
    if step == "subject":
        row = db_fetch_one(
            "SELECT id FROM subjects WHERE grade_id=%s AND name=%s",
            (st["grade_id"], text),
        )
        if not row:
            return await update.message.reply_text("هذه المادة غير صحيحة.")

        st["subject_id"] = row["id"]
        st["history"].append("subject")
        st["step"] = "option"

        rows = db_fetch_all("""
            SELECT so.name FROM subject_options so
            JOIN subject_option_map som ON so.id = som.option_id
            WHERE som.subject_id=%s
        """, (st["subject_id"],))

        if not rows:
            return await send_resources(update, st)

        return await update.message.reply_text(
            "اختر نوع المحتوى:",
            reply_markup=make_keyboard([r["name"] for r in rows]),
        )

    # OPTION
    if step == "option":
        row = db_fetch_one(
            "SELECT id FROM subject_options WHERE name=%s",
            (text,),
        )
        if not row:
            return await update.message.reply_text("الخيار غير صحيح.")

        st["option_id"] = row["id"]
        st["history"].append("option")
        st["step"] = "child_option"

        rows = db_fetch_all(
            "SELECT name FROM option_children WHERE option_id=%s",
            (row["id"],),
        )

        if not rows:
            return await send_resources(update, st)

        return await update.message.reply_text(
            "اختر الفصل أو الوحدة:",
            reply_markup=make_keyboard([r["name"] for r in rows]),
        )

    # CHILD UNIT
    if step == "child_option":
        row = db_fetch_one(
            "SELECT id FROM option_children WHERE option_id=%s AND name=%s",
            (st["option_id"], text),
        )
        if not row:
            return await update.message.reply_text("الخيار غير صحيح.")

        st["child_id"] = row["id"]
        st["history"].append("child_option")
        st["step"] = "subchild_option"

        rows = db_fetch_all(
            "SELECT name FROM option_subchildren WHERE child_id=%s",
            (row["id"],),
        )

        if not rows:
            st["step"] = "child_option"
            return await send_resources(update, st)

        return await update.message.reply_text(
            "اختر الدرس الفرعي:",
            reply_markup=make_keyboard([r["name"] for r in rows]),
        )

    # SUBCHILD
    if step == "subchild_option":
        row = db_fetch_one(
            "SELECT id FROM option_subchildren WHERE child_id=%s AND name=%s",
            (st["child_id"], text),
        )
        if not row:
            return await update.message.reply_text("الخيار غير صحيح.")

        st["subchild_id"] = row["id"]
        return await send_resources(update, st)
# ============================================================
#   FASTAPI APP & TELEGRAM LIFECYCLE
# ============================================================
app = FastAPI()
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

# Telegram Application (PTB v21)
ptb_application = (
    Application.builder()
    .token(BOT_TOKEN)
    .build()
)

ptb_application.add_handler(CommandHandler("start", start))
ptb_application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("INFO: Starting up application...")

    # Set Webhook
    await ptb_application.bot.set_webhook(url=f"{APP_URL}/webhook")
    log.info("Webhook set → %s/webhook", APP_URL)

    async with ptb_application:
        await ptb_application.start()
        log.info("Telegram bot started.")
        yield
        log.info("Shutting down bot...")
        await ptb_application.stop()
        conn.close()
        log.info("DB closed.")

app.router.lifespan_context = lifespan

# Webhook endpoint
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    await ptb_application.update_queue.put(
        Update.de_json(data, ptb_application.bot)
    )
    return Response(status_code=200)

# ============================================================
#   ADMIN HELPERS
# ============================================================
def build_resources_context():
    stages = db_fetch_all("SELECT id, name FROM stages ORDER BY id")
    terms = db_fetch_all("SELECT id, name, stage_id FROM terms ORDER BY id")
    grades = db_fetch_all("SELECT id, name, term_id FROM grades ORDER BY id")
    subjects = db_fetch_all("SELECT id, name, grade_id FROM subjects ORDER BY id")
    options = db_fetch_all("SELECT id, name FROM subject_options ORDER BY id")
    children = db_fetch_all("SELECT id, name, option_id FROM option_children ORDER BY id")
    subchildren = db_fetch_all("SELECT id, name, child_id FROM option_subchildren ORDER BY id")
    subjopt = db_fetch_all("SELECT subject_id, option_id FROM subject_option_map")

    resources = db_fetch_all("""
        SELECT id, title, url,
               stage_id, term_id, grade_id,
               subject_id, option_id, child_id, subchild_id
        FROM resources
        ORDER BY id DESC LIMIT 200
    """)

    stage_map = {x["id"]: x["name"] for x in stages}
    term_map = {x["id"]: x["name"] for x in terms}
    grade_map = {x["id"]: x["name"] for x in grades}
    subject_map = {x["id"]: x["name"] for x in subjects}
    option_map = {x["id"]: x["name"] for x in options}
    child_map = {x["id"]: x["name"] for x in children}
    sub_map = {x["id"]: x["name"] for x in subchildren}

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
            <td><a href="/admin/edit/{r['id']}" class="btn btn-warning btn-sm">تعديل</a></td>
            <td>
                <form method="post" action="/admin/delete/{r['id']}">
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
#   LOGIN PAGE
# ============================================================
@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <html dir='rtl'>
    <head>
        <meta charset='utf-8'>
        <title>تسجيل الدخول</title>
        <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css' rel='stylesheet'>
    </head>
    <body class='p-5' style='max-width:400px; margin:auto;'>
        <h3 class='mb-4'>🔐 تسجيل الدخول للوحة التحكم</h3>
        <form method='post' action='/login'>
            <label>اسم المستخدم:</label>
            <input name='username' class='form-control mb-3'>
            <label>كلمة المرور:</label>
            <input name='password' type='password' class='form-control mb-3'>
            <button class='btn btn-primary w-100'>دخول</button>
        </form>
    </body>
    </html>
    """

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == "admin" and password == ADMIN_PASSWORD:
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie("admin_auth", "yes")
        return resp
    return HTMLResponse("""
        <html dir='rtl'><body>
        <h3 style='color:red;'>❌ خطأ في البيانات</h3>
        <a href='/login'>المحاولة مرة أخرى</a>
        </body></html>
    """)

@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("admin_auth")
    return resp

# ============================================================
#   ADMIN DASHBOARD
# ============================================================
@app.get("/admin", response_class=HTMLResponse)
def admin_panel(admin_auth: str | None = Cookie(None)):
    if admin_auth != "yes":
        return RedirectResponse("/login")

    ctx = build_resources_context()
    template = (BASE_DIR / "admin_template.html").read_text("utf-8")

    template = template.replace("__ROWS__", ctx["rows_html"])
    template = template.replace("__STAGES__", json.dumps(ctx["stages"], ensure_ascii=False))
    template = template.replace("__TERMS__", json.dumps(ctx["terms"], ensure_ascii=False))
    template = template.replace("__GRADES__", json.dumps(ctx["grades"], ensure_ascii=False))
    template = template.replace("__SUBJECTS__", json.dumps(ctx["subjects"], ensure_ascii=False))
    template = template.replace("__OPTIONS__", json.dumps(ctx["options"], ensure_ascii=False))
    template = template.replace("__CHILDREN__", json.dumps(ctx["children"], ensure_ascii=False))
    template = template.replace("__SUBCHILDREN__", json.dumps(ctx["subchildren"], ensure_ascii=False))
    template = template.replace("__SUBJOPT__", json.dumps(ctx["subjopt"], ensure_ascii=False))

    return HTMLResponse(template)

# ============================================================
#   ADD RESOURCE (NO PASSWORD)
# ============================================================
@app.post("/admin/add")
async def admin_add(
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
    admin_auth: str | None = Cookie(None),
):
    if admin_auth != "yes":
        return RedirectResponse("/login")

    if file and url.strip():
        raise HTTPException(400, "لا يمكن رفع PDF وإدخال رابط معًا")

    final_url = url.strip()
    if file and file.filename:
        final_url = await save_uploaded_file(file)

    if not final_url:
        raise HTTPException(400, "يجب إدخال رابط أو ملف PDF")

    sub_val = int(subchild_id) if subchild_id else None

    db_execute("""
        INSERT INTO resources (subject_id, option_id, child_id, subchild_id,
                               stage_id, term_id, grade_id, title, url)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        subject_id, option_id, child_id, sub_val,
        stage_id, term_id, grade_id, title, final_url,
    ))

    return RedirectResponse("/admin", status_code=303)

# ============================================================
#   EDIT RESOURCE
# ============================================================
@app.get("/admin/edit/{rid}", response_class=HTMLResponse)
def edit_page(rid: int, admin_auth: str | None = Cookie(None)):
    if admin_auth != "yes":
        return RedirectResponse("/login")

    row = db_fetch_one("SELECT * FROM resources WHERE id=%s", (rid,))
    if not row:
        raise HTTPException(404, "غير موجود")

    return HTMLResponse(f"""
    <html dir='rtl'>
    <head>
        <meta charset='utf-8'>
        <title>تعديل</title>
        <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css' rel='stylesheet'>
    </head>
    <body class='p-4'>
        <h3>تعديل المورد {rid}</h3>
        <form method='post' enctype='multipart/form-data'>
            <label>العنوان:</label>
            <input name='title' class='form-control' value="{row['title']}">

            <label class='mt-3'>الرابط:</label>
            <input name='url' class='form-control' value="{row['url']}">

            <label class='mt-3'>PDF جديد (اختياري):</label>
            <input type='file' name='file' accept='.pdf' class='form-control'>

            <button class='btn btn-success mt-3'>حفظ</button>
        </form>
        <a href='/admin' class='btn btn-secondary mt-3'>رجوع</a>
    </body>
    </html>
    """)

@app.post("/admin/edit/{rid}")
async def save_edit(
    rid: int,
    title: str = Form(...),
    url: str = Form(""),
    file: UploadFile | None = File(None),
    admin_auth: str | None = Cookie(None),
):
    if admin_auth != "yes":
        return RedirectResponse("/login")

    final_url = url.strip()
    if file and file.filename:
        final_url = await save_uploaded_file(file)

    if not final_url:
        raise HTTPException(400, "يجب إدخال رابط أو PDF")

    db_execute(
        "UPDATE resources SET title=%s, url=%s WHERE id=%s",
        (title, final_url, rid),
    )

    return RedirectResponse("/admin", status_code=303)

# ============================================================
#   DELETE RESOURCE
# ============================================================
@app.post("/admin/delete/{rid}")
def delete_resource(rid: int, admin_auth: str | None = Cookie(None)):
    if admin_auth != "yes":
        return RedirectResponse("/login")

    db_execute("DELETE FROM resources WHERE id=%s", (rid,))
    return RedirectResponse("/admin", status_code=303)
