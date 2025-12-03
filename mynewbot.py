# ============================================================
#   IMPORTS & CONFIG
# ============================================================
import os
import uuid
import json
import logging
from pathlib import Path
from contextlib import asynccontextmanager

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

# طباعة مختصرة للـ DB URL بدون الباسورد
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
    """Fetch all rows as list of dicts."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def db_fetch_one(query: str, params=()):
    """Fetch single row as dict or None."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchone()


def db_execute(query: str, params=()):
    """Execute INSERT/UPDATE/DELETE."""
    with conn.cursor() as cur:
        cur.execute(query, params)


# ============================================================
#   INIT DB (CREATE TABLES IF NOT EXISTS)
# ============================================================
def init_db_pg():
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS stages (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS terms (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            stage_id INTEGER NOT NULL REFERENCES stages(id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS grades (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            term_id INTEGER NOT NULL REFERENCES terms(id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            grade_id INTEGER NOT NULL REFERENCES grades(id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS subject_options (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS subject_option_map (
            subject_id INTEGER NOT NULL REFERENCES subjects(id),
            option_id INTEGER NOT NULL REFERENCES subject_options(id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS option_children (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            option_id INTEGER NOT NULL REFERENCES subject_options(id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS option_subchildren (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            child_id INTEGER NOT NULL REFERENCES option_children(id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER REFERENCES subjects(id),
            option_id INTEGER REFERENCES subject_options(id),
            child_id INTEGER REFERENCES option_children(id),
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            subchild_id INTEGER REFERENCES option_subchildren(id),
            stage_id INTEGER REFERENCES stages(id),
            term_id INTEGER REFERENCES terms(id),
            grade_id INTEGER REFERENCES grades(id)
        );
        """)

    log.info("✅ PostgreSQL tables ensured.")


init_db_pg()

# ============================================================
#   UTILS: SAVE FILE
# ============================================================
async def save_uploaded_file(file: UploadFile) -> str | None:
    """Save uploaded PDF with unique name and return its public URL."""
    if not file or not file.filename:
        return None

    ext = Path(file.filename).suffix or ".pdf"
    unique_name = f"{uuid.uuid4()}{ext}"
    save_path = UPLOAD_DIR / unique_name

    content = await file.read()
    save_path.write_bytes(content)

    log.info(f"📁 Saved file: {unique_name}")
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
        row = labels[i:i+2]
        row.reverse()
        rows.append(row)
    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ============================================================
#   SEND RESOURCES
# ============================================================
async def send_resources(update: Update, state: dict):
    resources = db_fetch_all(
        """
        SELECT title, url FROM resources
        WHERE stage_id = %s AND term_id = %s AND grade_id = %s
          AND subject_id = %s AND option_id = %s AND child_id = %s
          AND (
                subchild_id = %s
             OR (subchild_id IS NULL AND %s IS NULL)
             OR (subchild_id = 0 AND %s IS NULL)
          )
        """,
        (
            state["stage_id"],
            state["term_id"],
            state["grade_id"],
            state["subject_id"],
            state["option_id"],
            state["child_id"],
            state.get("subchild_id"),
            state.get("subchild_id"),
            state.get("subchild_id"),
        ),
    )

    if not resources:
        return await update.message.reply_text("لا يوجد محتوى.")

    msg = "\n".join(
        f"▪️ <a href='{r['url']}'>{r['title']}</a>" for r in resources
    )

    await update.message.reply_text(
        msg, parse_mode="HTML", disable_web_page_preview=True
    )


# ============================================================
#   /START COMMAND
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    stages = db_fetch_all("SELECT id, name FROM stages ORDER BY id")
    stage_names = [s["name"] for s in stages]

    welcome = (
        "✨ *منصة نيو أكاديمي التعليمية* ✨\n"
        "مرحباً بكم ❤️\n\n"
        "📚 *اختر المرحلة للبدء:*"
    )

    await update.message.reply_text(
        welcome,
        reply_markup=make_keyboard(stage_names),
        parse_mode="Markdown",
    )
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

    # -------- BACK BUTTON --------
    if text == "رجوع ↩️":
        back_map = {
            "subchild": ("suboption",
                "SELECT name FROM option_children WHERE option_id = %s",
                (state.get("option_id"),),
                "اختر القسم:"
            ),
            "suboption": ("option",
                """
                SELECT so.name
                FROM subject_option_map som
                JOIN subject_options so ON so.id = som.option_id
                WHERE som.subject_id = %s
                """,
                (state.get("subject_id"),),
                "اختر نوع المحتوى:"
            ),
            "option": ("subject",
                "SELECT name FROM subjects WHERE grade_id = %s",
                (state.get("grade_id"),),
                "اختر المادة:"
            ),
            "subject": ("grade",
                "SELECT name FROM grades WHERE term_id = %s",
                (state.get("term_id"),),
                "اختر الصف:"
            ),
            "grade": ("term",
                "SELECT name FROM terms WHERE stage_id = %s",
                (state.get("stage_id"),),
                "اختر الفصل:"
            ),
            "term": ("stage",
                "SELECT name FROM stages ORDER BY id",
                (),
                "اختر المرحلة:"
            ),
        }

        if step in back_map:
            new_step, query, params, msg = back_map[step]
            state["step"] = new_step
            rows = db_fetch_all(query, params)
            names = [r["name"] for r in rows]
            return await update.message.reply_text(
                msg, reply_markup=make_keyboard(names)
            )

        return await start(update, context)

    # -------- STAGE --------
    if step == "stage":
        row = db_fetch_one(
            "SELECT id FROM stages WHERE name = %s", (text,)
        )
        if not row:
            return
        state["stage_id"] = row["id"]
        state["step"] = "term"

        terms = db_fetch_all(
            "SELECT name FROM terms WHERE stage_id = %s",
            (state["stage_id"],),
        )
        names = [t["name"] for t in terms]
        return await update.message.reply_text(
            "اختر الفصل:", reply_markup=make_keyboard(names)
        )

    # -------- TERM --------
    if step == "term":
        row = db_fetch_one(
            "SELECT id FROM terms WHERE name = %s AND stage_id = %s",
            (text, state["stage_id"]),
        )
        if not row:
            return
        state["term_id"] = row["id"]
        state["step"] = "grade"

        grades = db_fetch_all(
            "SELECT name FROM grades WHERE term_id = %s",
            (state["term_id"],),
        )
        names = [g["name"] for g in grades]
        return await update.message.reply_text(
            "اختر الصف:", reply_markup=make_keyboard(names)
        )

    # -------- GRADE --------
    if step == "grade":
        row = db_fetch_one(
            "SELECT id FROM grades WHERE name = %s AND term_id = %s",
            (text, state["term_id"]),
        )
        if not row:
            return
        state["grade_id"] = row["id"]
        state["step"] = "subject"

        subs = db_fetch_all(
            "SELECT name FROM subjects WHERE grade_id = %s",
            (state["grade_id"],),
        )
        names = [s["name"] for s in subs]
        return await update.message.reply_text(
            "اختر المادة:", reply_markup=make_keyboard(names)
        )

    # -------- SUBJECT --------
    if step == "subject":
        row = db_fetch_one(
            "SELECT id FROM subjects WHERE name = %s AND grade_id = %s",
            (text, state["grade_id"]),
        )
        if not row:
            return
        state["subject_id"] = row["id"]
        state["step"] = "option"

        opts = db_fetch_all(
            """
            SELECT so.id, so.name
            FROM subject_option_map som
            JOIN subject_options so ON so.id = som.option_id
            WHERE som.subject_id = %s
            """,
            (state["subject_id"],),
        )
        names = [o["name"] for o in opts]

        return await update.message.reply_text(
            "اختر نوع المحتوى:", reply_markup=make_keyboard(names)
        )

    # -------- OPTION --------
    if step == "option":
        row = db_fetch_one(
            "SELECT id FROM subject_options WHERE name = %s",
            (text,),
        )
        if not row:
            return
        state["option_id"] = row["id"]
        state["step"] = "suboption"

        children = db_fetch_all(
            "SELECT name FROM option_children WHERE option_id = %s",
            (state["option_id"],),
        )
        names = [c["name"] for c in children]

        return await update.message.reply_text(
            "اختر القسم:", reply_markup=make_keyboard(names)
        )

    # -------- SUBOPTION --------
    if step == "suboption":
        row = db_fetch_one(
            "SELECT id FROM option_children WHERE name = %s AND option_id = %s",
            (text, state["option_id"]),
        )
        if not row:
            return
        state["child_id"] = row["id"]

        subs = db_fetch_all(
            "SELECT name FROM option_subchildren WHERE child_id = %s",
            (state["child_id"],),
        )

        if subs:
            state["step"] = "subchild"
            names = [s["name"] for s in subs]
            return await update.message.reply_text(
                "اختر القسم الفرعي:", reply_markup=make_keyboard(names)
            )

        return await send_resources(update, state)

    # -------- SUBCHILD --------
    if step == "subchild":
        row = db_fetch_one(
            "SELECT id FROM option_subchildren WHERE name = %s AND child_id = %s",
            (text, state["child_id"]),
        )
        if not row:
            return
        state["subchild_id"] = row["id"]

        return await send_resources(update, state)


# ============================================================
#   FASTAPI APP + TELEGRAM WEBHOOK
# ============================================================
app = FastAPI(title="Edu Bot API", lifespan=lifespan)

# Static files for uploaded PDFs
app.mount("/files", StaticFiles(directory=str(UPLOAD_DIR)), name="files")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 Initializing Telegram bot...")

    # 1) Create Telegram Application ONCE
    tg_app = Application.builder().token(BOT_TOKEN).build()

    # 2) Register Handlers
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # 3) Initialize the Application (IMPORTANT)
    await tg_app.initialize()

    # 4) Start Telegram Application (REQUIRED)
    await tg_app.start()

    # 5) Set webhook AFTER start
    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")

    # 6) Save the Application so webhook can use it
    app.state.tg_application = tg_app

    log.info("✅ Bot is running & webhook is active.")

    yield

    # 7) Clean shutdown
    log.info("🛑 Stopping Telegram bot...")
    await tg_app.stop()
    await tg_app.shutdown()

# ============================================================
#   TELEGRAM WEBHOOK ENDPOINT
# ============================================================
@app.post("/telegram")
async def telegram_webhook(request: Request):
    update = Update.de_json(await request.json(), app.state.tg_application.bot)
    await app.state.tg_application.process_update(update)
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
        SELECT id, title, url,
               stage_id, term_id, grade_id,
               subject_id, option_id, child_id, subchild_id
        FROM resources
        ORDER BY id DESC
        LIMIT 200
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
                      onsubmit="return confirm('حذف نهائي؟');">
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
        raise HTTPException(
            status_code=500,
            detail="admin_template.html غير موجود في نفس المجلد."
        )

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
    file: UploadFile | None = File(None),
):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="كلمة المرور غير صحيحة")

    if url.strip() and file and file.filename:
        raise HTTPException(
            status_code=400,
            detail="اختاري رابط أو PDF فقط، وليس الاثنين معًا."
        )

    final_url = url.strip()

    if file and file.filename:
        file_url = await save_uploaded_file(file)
        if not file_url:
            raise HTTPException(status_code=500, detail="فشل في حفظ الملف.")
        final_url = file_url

    if not final_url:
        raise HTTPException(
            status_code=400,
            detail="يجب إدخال رابط أو رفع ملف PDF."
        )

    sub_val = int(subchild_id) if subchild_id.strip() else None

    dup = db_fetch_one(
        """
        SELECT id FROM resources
        WHERE stage_id = %s AND term_id = %s AND grade_id = %s
          AND subject_id = %s AND option_id = %s AND child_id = %s
          AND (
                (%s IS NULL AND subchild_id IS NULL)
             OR subchild_id = %s
          )
          AND title = %s
        """,
        (
            stage_id, term_id, grade_id,
            subject_id, option_id, child_id,
            sub_val, sub_val, title
        ),
    )

    if dup:
        rid = dup["id"]
        return HTMLResponse(
            f"""
            <html dir='rtl'><body style="font-family:Tahoma; padding:20px;">
            <h3>⚠️ هذا المحتوى موجود بالفعل</h3>
            <p>يمكنك تعديل العنصر أو حذفه:</p>

            <a href="/admin/edit/{rid}">
                <button style="padding:10px 16px;margin:5px;
                    background:#28a745;color:white;border:none;border-radius:6px;cursor:pointer;">
                    تعديل المحتوى ✏️
                </button>
            </a>

            <form action="/admin/delete/{rid}" method="post" style="display:inline-block;margin:5px;">
                <input type="password" name="password" placeholder="كلمة السر" required
                       style="margin-left:8px;padding:4px 8px;">
                <button style="padding:10px 16px;
                    background:#dc3545;color:white;border:none;border-radius:6px;cursor:pointer;">
                    حذف المحتوى 🗑️
                </button>
            </form>

            <br><br>
            <a href="/admin">
                <button style="padding:10px 16px;
                    background:#6c757d;color:white;border:none;border-radius:6px;cursor:pointer;">
                    الرجوع للوحة التحكم
                </button>
            </a>
            </body></html>
            """
        )

    db_execute(
        """
        INSERT INTO resources (
            subject_id, option_id, child_id,
            title, url, subchild_id,
            stage_id, term_id, grade_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            subject_id, option_id, child_id,
            title, final_url, sub_val,
            stage_id, term_id, grade_id,
        ),
    )

    log.info(f"✅ Added resource: {title}")
    return RedirectResponse("/admin", status_code=303)


# ============================================================
#   ADMIN: EDIT PAGE
# ============================================================
@app.get("/admin/edit/{rid}", response_class=HTMLResponse)
def admin_edit_page(rid: int):
    r = db_fetch_one(
        "SELECT id, title, url FROM resources WHERE id = %s",
        (rid,),
    )
    if not r:
        raise HTTPException(status_code=404, detail="المورد غير موجود.")

    return HTMLResponse(
        f"""
        <html dir="rtl">
        <head>
            <meta charset="utf-8">
            <title>تعديل البيانات</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>

        <body class="p-4">
            <h3 class="mb-3">✏️ تعديل الرابط رقم {r['id']}</h3>

            <form method="post" enctype="multipart/form-data">
                <label class="mt-2">العنوان:</label>
                <input name="title" class="form-control" value="{r['title']}">

                <label class="mt-3">الرابط:</label>
                <input name="url" class="form-control" value="{r['url'] or ''}">

                <label class="mt-3">رفع PDF جديد (اختياري):</label>
                <input type="file" name="file" class="form-control" accept=".pdf">

                <button class="btn btn-success mt-4">💾 حفظ التعديلات</button>
            </form>

            <a href="/admin" class="btn btn-secondary mt-3">⬅️ رجوع</a>
        </body>
        </html>
        """
    )


# ============================================================
#   ADMIN: SAVE EDIT
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
        if file_url:
            final_url = file_url

    if not final_url:
        raise HTTPException(
            status_code=400,
            detail="يجب إدخال رابط أو رفع ملف."
        )

    db_execute(
        "UPDATE resources SET title = %s, url = %s WHERE id = %s",
        (title, final_url, rid),
    )

    log.info(f"✏️ Resource {rid} updated.")
    return RedirectResponse("/admin", status_code=303)


# ============================================================
#   ADMIN: DELETE
# ============================================================
@app.post("/admin/delete/{rid}")
def admin_delete(rid: int, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="كلمة المرور غير صحيحة")

    db_execute("DELETE FROM resources WHERE id = %s", (rid,))
    log.info(f"🗑️ Resource {rid} deleted.")
    return RedirectResponse("/admin", status_code=303)
