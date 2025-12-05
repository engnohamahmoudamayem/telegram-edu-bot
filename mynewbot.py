# ============================================================
#   IMPORTS & CONFIG
# ============================================================
import os
import uuid
import json
import logging
from pathlib import Path

import psycopg2
import psycopg2.extras

from fastapi import FastAPI, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, Bot

# ----------------- SESSIONS FOR ADMIN LOGIN -----------------
from starlette.middleware.sessions import SessionMiddleware


# ============================================================
#   LOAD ENV
# ============================================================
load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("BOT_TOKEN or APP_URL missing!")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL missing!")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD missing from ENV!")

# نظف الباسورد من أى مسافات / أسطر
ADMIN_PASSWORD = ADMIN_PASSWORD.strip()
print("🔥 CLEAN ADMIN_PASSWORD =", repr(ADMIN_PASSWORD))
print("🔥 RUNNING FILE =", __file__)
import telegram.ext
print("🔥 Telegram EXT Version:", telegram.ext.__version__)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("EDU_BOT")

# ============================================================
#   TELEGRAM BOT (بدون Application / Updater)
# ============================================================
bot = Bot(BOT_TOKEN)


# ============================================================
#   CONNECT TO POSTGRESQL
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

    cur.execute("""CREATE TABLE IF NOT EXISTS stages (id SERIAL PRIMARY KEY, name TEXT UNIQUE);""")
    cur.execute("""CREATE TABLE IF NOT EXISTS terms (id SERIAL PRIMARY KEY, name TEXT, stage_id INTEGER REFERENCES stages(id));""")
    cur.execute("""CREATE TABLE IF NOT EXISTS grades (id SERIAL PRIMARY KEY, name TEXT, term_id INTEGER REFERENCES terms(id));""")
    cur.execute("""CREATE TABLE IF NOT EXISTS subjects (id SERIAL PRIMARY KEY, name TEXT, grade_id INTEGER REFERENCES grades(id));""")
    cur.execute("""CREATE TABLE IF NOT EXISTS subject_options (id SERIAL PRIMARY KEY, name TEXT);""")
    cur.execute("""CREATE TABLE IF NOT EXISTS subject_option_map (subject_id INTEGER REFERENCES subjects(id), option_id INTEGER REFERENCES subject_options(id));""")
    cur.execute("""CREATE TABLE IF NOT EXISTS option_children (id SERIAL PRIMARY KEY, name TEXT, option_id INTEGER REFERENCES subject_options(id));""")
    cur.execute("""CREATE TABLE IF NOT EXISTS option_subchildren (id SERIAL PRIMARY KEY, name TEXT, child_id INTEGER REFERENCES option_children(id));""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER REFERENCES subjects(id),
            option_id INTEGER REFERENCES subject_options(id),
            child_id INTEGER REFERENCES option_children(id),
            subchild_id INTEGER REFERENCES option_subchildren(id),
            stage_id INTEGER REFERENCES stages(id),
            term_id INTEGER REFERENCES terms(id),
            grade_id INTEGER REFERENCES grades(id),
            title TEXT NOT NULL,
            url TEXT NOT NULL
        );
    """)

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
#   BOT STATE + KEYBOARD + HISTORY (BACK SYSTEM)
# ============================================================
user_state = {}


def make_keyboard(opts):
    rows = []
    for i in range(0, len(opts), 2):
        r = opts[i:i+2]
        r.reverse()
        rows.append(r)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ============================================================
#   SEND RESOURCES
# ============================================================
async def send_resources(update: Update, st: dict):
    rows = db_fetch_all(
        """
        SELECT title, url FROM resources
        WHERE stage_id=%s AND term_id=%s AND grade_id=%s
          AND subject_id=%s AND option_id=%s AND child_id=%s
          AND (subchild_id=%s OR subchild_id IS NULL)
        """,
        (
            st["stage_id"],
            st["term_id"],
            st["grade_id"],
            st["subject_id"],
            st["option_id"],
            st["child_id"],
            st.get("subchild_id"),
        ),
    )

    if not rows:
        return await update.message.reply_text("لا يوجد محتوى.")

    msg = "\n".join(f"▪ <a href='{r['url']}'>{r['title']}</a>" for r in rows)
    await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)


# ============================================================
#   /START
# ============================================================
async def start(update: Update):
    cid = update.effective_chat.id
    user_state[cid] = {"step": "stage", "history": []}

    rows = db_fetch_all("SELECT name FROM stages ORDER BY id")
    await update.message.reply_text(
        "✨ *منصة نيو أكاديمي التعليمية* ✨\nاختر المرحلة:",
        reply_markup=make_keyboard([r["name"] for r in rows]),
        parse_mode="Markdown",
    )


# ============================================================
#   HANDLE MESSAGE + SMART BACK SYSTEM
# ============================================================
async def handle_message(update: Update):
    cid = update.effective_chat.id
    text = (update.message.text or "").strip()

    if cid not in user_state:
        return await start(update)

    st = user_state[cid]
    step = st["step"]

    # ---------------- BACK BUTTON ----------------
    if text == "رجوع ↩️":
        if not st["history"]:
            return await start(update)

        prev = st["history"].pop()
        st["step"] = prev

        if prev == "stage":
            rows = db_fetch_all("SELECT name FROM stages ORDER BY id")
            return await update.message.reply_text(
                "اختر المرحلة:", reply_markup=make_keyboard([r["name"] for r in rows])
            )

        if prev == "term":
            rows = db_fetch_all("SELECT name FROM terms WHERE stage_id=%s", (st["stage_id"],))
            return await update.message.reply_text(
                "اختر الفصل:", reply_markup=make_keyboard([r["name"] for r in rows])
            )

        if prev == "grade":
            rows = db_fetch_all("SELECT name FROM grades WHERE term_id=%s", (st["term_id"],))
            return await update.message.reply_text(
                "اختر الصف:", reply_markup=make_keyboard([r["name"] for r in rows])
            )

        if prev == "subject":
            rows = db_fetch_all("SELECT name FROM subjects WHERE grade_id=%s", (st["grade_id"],))
            return await update.message.reply_text(
                "اختر المادة:", reply_markup=make_keyboard([r["name"] for r in rows])
            )

        if prev == "option":
            rows = db_fetch_all(
                """
                SELECT so.name
                FROM subject_option_map som
                JOIN subject_options so ON so.id=som.option_id
                WHERE som.subject_id=%s
            """,
                (st["subject_id"],),
            )
            return await update.message.reply_text(
                "اختر نوع المحتوى:", reply_markup=make_keyboard([r["name"] for r in rows])
            )

        if prev == "suboption":
            rows = db_fetch_all("SELECT name FROM option_children WHERE option_id=%s", (st["option_id"],))
            return await update.message.reply_text(
                "اختر القسم:", reply_markup=make_keyboard([r["name"] for r in rows])
            )

        if prev == "subchild":
            rows = db_fetch_all("SELECT name FROM option_subchildren WHERE child_id=%s", (st["child_id"],))
            return await update.message.reply_text(
                "اختر القسم الفرعي:", reply_markup=make_keyboard([r["name"] for r in rows])
            )

    # ------------- NORMAL FORWARD FLOW --------------
    # stage → term
    if step == "stage":
        row = db_fetch_one("SELECT id FROM stages WHERE name=%s", (text,))
        if not row:
            return
        st["stage_id"] = row["id"]
        st["history"].append("stage")
        st["step"] = "term"

        rows = db_fetch_all("SELECT name FROM terms WHERE stage_id=%s", (row["id"],))
        return await update.message.reply_text(
            "اختر الفصل:", reply_markup=make_keyboard([r["name"] for r in rows])
        )

    # term → grade
    if step == "term":
        row = db_fetch_one(
            "SELECT id FROM terms WHERE name=%s AND stage_id=%s", (text, st["stage_id"])
        )
        if not row:
            return
        st["term_id"] = row["id"]
        st["history"].append("term")
        st["step"] = "grade"

        rows = db_fetch_all("SELECT name FROM grades WHERE term_id=%s", (row["id"],))
        return await update.message.reply_text(
            "اختر الصف:", reply_markup=make_keyboard([r["name"] for r in rows])
        )

    # grade → subject
    if step == "grade":
        row = db_fetch_one(
            "SELECT id FROM grades WHERE name=%s AND term_id=%s", (text, st["term_id"])
        )
        if not row:
            return
        st["grade_id"] = row["id"]
        st["history"].append("grade")
        st["step"] = "subject"

        rows = db_fetch_all("SELECT name FROM subjects WHERE grade_id=%s", (row["id"],))
        return await update.message.reply_text(
            "اختر المادة:", reply_markup=make_keyboard([r["name"] for r in rows])
        )

    # subject → option
    if step == "subject":
        row = db_fetch_one(
            "SELECT id FROM subjects WHERE name=%s AND grade_id=%s", (text, st["grade_id"])
        )
        if not row:
            return
        st["subject_id"] = row["id"]
        st["history"].append("subject")
        st["step"] = "option"

        rows = db_fetch_all(
            """
            SELECT so.name
            FROM subject_option_map som
            JOIN subject_options so ON som.option_id=so.id
            WHERE som.subject_id=%s
        """,
            (row["id"],),
        )
        return await update.message.reply_text(
            "اختر نوع المحتوى:", reply_markup=make_keyboard([r["name"] for r in rows])
        )

    # option → suboption
    if step == "option":
        row = db_fetch_one("SELECT id FROM subject_options WHERE name=%s", (text,))
        if not row:
            return
        st["option_id"] = row["id"]
        st["history"].append("option")
        st["step"] = "suboption"

        rows = db_fetch_all("SELECT name FROM option_children WHERE option_id=%s", (row["id"],))
        return await update.message.reply_text(
            "اختر القسم:", reply_markup=make_keyboard([r["name"] for r in rows])
        )

    # suboption → subchild or resources
    if step == "suboption":
        row = db_fetch_one(
            "SELECT id FROM option_children WHERE name=%s AND option_id=%s",
            (text, st["option_id"]),
        )
        if not row:
            return

        st["child_id"] = row["id"]
        st["history"].append("suboption")

        rows = db_fetch_all("SELECT name FROM option_subchildren WHERE child_id=%s", (row["id"],))

        if rows:
            st["step"] = "subchild"
            return await update.message.reply_text(
                "اختر القسم الفرعي:", reply_markup=make_keyboard([r["name"] for r in rows])
            )

        st["step"] = "done"
        return await send_resources(update, st)

    # subchild → resources
    if step == "subchild":
        row = db_fetch_one(
            "SELECT id FROM option_subchildren WHERE name=%s AND child_id=%s",
            (text, st["child_id"]),
        )
        if not row:
            return
        st["subchild_id"] = row["id"]
        st["history"].append("subchild")
        st["step"] = "done"

        return await send_resources(update, st)


# ============================================================
#   FASTAPI APP + SESSIONS
# ============================================================
app = FastAPI(title="Edu Bot API")
app.add_middleware(SessionMiddleware, secret_key="CHANGE_THIS_SECRET_KEY")
app.mount("/files", StaticFiles(directory=str(UPLOAD_DIR)), name="files")


# ============================================================
#   TELEGRAM WEBHOOK ENDPOINT
# ============================================================
@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot)
    if update.message:
        text = update.message.text or ""
        if text.startswith("/start"):
            await start(update)
        else:
            await handle_message(update)
    return Response(status_code=200)


# اختيارى: صفحة بسيطة فى الجذر
@app.get("/")
def root():
    return RedirectResponse("/admin/login")


# ============================================================
#   LOGIN PAGE
# ============================================================
@app.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request):
    return """
    <html dir='rtl'>
    <head>
        <meta charset='utf-8'>
        <title>تسجيل الدخول</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="p-5" style="background:#f6f6f6;">
        <div class="container" style="max-width:400px;">
            <div class="card shadow p-4">
                <h3 class="text-center mb-4">🔐 تسجيل الدخول</h3>
                <form method="post">
                    <div class="mb-3">
                        <label class="form-label">كلمة السر</label>
                        <input type="password" name="password" class="form-control" required placeholder="أدخل كلمة السر">
                    </div>
                    <button class="btn btn-primary w-100">دخول</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """


# ============================================================
#   LOGIN SUBMIT
# ============================================================
@app.post("/admin/login")
async def login_submit(request: Request):
    form = await request.form()
    password = form.get("password")

    if password == ADMIN_PASSWORD:
        request.session["admin_logged"] = True
        return RedirectResponse("/admin", 303)

    return HTMLResponse(
        """
        <h3 style='color:red;text-align:center;margin-top:40px;'>❌ كلمة السر غير صحيحة</h3>
        <meta http-equiv='refresh' content='1; url=/admin/login'>
    """
    )


# ============================================================
#   ADMIN HELPER
# ============================================================
def build_resources_context():
    stages = db_fetch_all("SELECT id,name FROM stages ORDER BY id")
    terms = db_fetch_all("SELECT id,name,stage_id FROM terms ORDER BY id")
    grades = db_fetch_all("SELECT id,name,term_id FROM grades ORDER BY id")
    subjects = db_fetch_all("SELECT id,name,grade_id FROM subjects ORDER BY id")
    options = db_fetch_all("SELECT id,name FROM subject_options ORDER BY id")
    children = db_fetch_all("SELECT id,name,option_id FROM option_children ORDER BY id")
    subchildren = db_fetch_all("SELECT id,name,child_id FROM option_subchildren ORDER BY id")
    subjopt = db_fetch_all("SELECT subject_id,option_id FROM subject_option_map")

    resources = db_fetch_all(
        """
        SELECT * FROM resources ORDER BY id DESC LIMIT 200
    """
    )

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
            <td>{stage_map.get(r['stage_id'],'')}</td>
            <td>{term_map.get(r['term_id'],'')}</td>
            <td>{grade_map.get(r['grade_id'],'')}</td>
            <td>{subject_map.get(r['subject_id'],'')}</td>
            <td>{option_map.get(r['option_id'],'')}</td>
            <td>{child_map.get(r['child_id'],'')}</td>
            <td>{sub_map.get(r['subchild_id'],'') if r['subchild_id'] else ''}</td>
            <td>{r['title']}</td>
            <td><a href="{r['url']}" target="_blank">فتح</a></td>
            <td><a class="btn btn-warning btn-sm" href="/admin/edit/{r['id']}">تعديل</a></td>
            <td>
                <form method="post" action="/admin/delete/{r['id']}">
                    <input name="password" type="password" class="form-control form-control-sm mb-1" required placeholder="كلمة السر">
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
#   ADMIN PAGE (PROTECTED)
# ============================================================
@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    if not request.session.get("admin_logged"):
        return RedirectResponse("/admin/login")

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
#   ADMIN ADD (PROTECTED)
# ============================================================
@app.post("/admin/add")
async def admin_add(
    request: Request,
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
    password: str = Form(...),
):

    if password != ADMIN_PASSWORD:
        raise HTTPException(401, "كلمة السر خطأ!")

    final_url = url.strip()
    if file and file.filename:
        final_url = await save_uploaded_file(file)

    if not final_url:
        raise HTTPException(400, "يجب إدخال رابط أو PDF")

    sub_val = int(subchild_id) if subchild_id.strip() else None

    db_execute(
        """
        INSERT INTO resources (
            subject_id,option_id,child_id,subchild_id,
            stage_id,term_id,grade_id,title,url
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """,
        (subject_id, option_id, child_id, sub_val, stage_id, term_id, grade_id, title, final_url),
    )

    return RedirectResponse("/admin", 303)


# ============================================================
#   EDIT PAGE
# ============================================================
@app.get("/admin/edit/{rid}", response_class=HTMLResponse)
def edit_page(request: Request, rid: int):

    if not request.session.get("admin_logged"):
        return RedirectResponse("/admin/login")

    row = db_fetch_one("SELECT * FROM resources WHERE id=%s", (rid,))
    if not row:
        raise HTTPException(404, "غير موجود")

    return HTMLResponse(
        f"""
    <html dir="rtl">
    <head>
        <meta charset="utf-8">
        <title>تعديل المورد</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="p-4">
    <h3>تعديل المورد {rid}</h3>

    <form method="post" enctype="multipart/form-data">
        <div class="mb-3">
            <label>العنوان:</label>
            <input name="title" class="form-control" value="{row['title']}">
        </div>

        <div class="mb-3">
            <label>الرابط:</label>
            <input name="url" class="form-control" value="{row['url']}">
        </div>

        <div class="mb-3">
            <label>PDF جديد (اختياري):</label>
            <input type="file" name="file" class="form-control" accept=".pdf">
        </div>

        <div class="mb-3">
            <label>كلمة السر:</label>
            <input type="password" name="password" required class="form-control">
        </div>

        <button class="btn btn-success">حفظ</button>
    </form>

    <a href="/admin" class="btn btn-secondary mt-3">رجوع</a>

    </body></html>
    """
    )


# ============================================================
#   SAVE EDIT
# ============================================================
@app.post("/admin/edit/{rid}")
async def save_edit(
    request: Request,
    rid: int,
    title: str = Form(...),
    url: str = Form(""),
    file: UploadFile | None = File(None),
    password: str = Form(...),
):

    if password != ADMIN_PASSWORD:
        raise HTTPException(401, "كلمة السر خطأ!")

    final_url = url.strip()
    if file and file.filename:
        final_url = await save_uploaded_file(file)

    db_execute("UPDATE resources SET title=%s,url=%s WHERE id=%s", (title, final_url, rid))

    return RedirectResponse("/admin", 303)


# ============================================================
#   DELETE RESOURCE
# ============================================================
@app.post("/admin/delete/{rid}")
async def delete_resource(request: Request, rid: int, password: str = Form(...)):

    if password != ADMIN_PASSWORD:
        raise HTTPException(401, "كلمة السر خطأ!")

    db_execute("DELETE FROM resources WHERE id=%s", (rid,))
    return RedirectResponse("/admin", 303)
