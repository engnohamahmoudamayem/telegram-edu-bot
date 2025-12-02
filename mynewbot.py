# ============================================================
#   IMPORTS & PATHS
# ============================================================
import os
import logging
from contextlib import asynccontextmanager
import json

import psycopg2
from psycopg2.extras import DictCursor

from fastapi import FastAPI, Request, Response, Form, UploadFile, File
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
from dotenv import load_dotenv

# ============================================================
#   ENV & DB
# ============================================================
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DATABASE_URL = os.environ.get("DATABASE_URL")

if not BOT_TOKEN or not APP_URL or not DATABASE_URL:
    raise RuntimeError("❌ BOT_TOKEN أو APP_URL أو DATABASE_URL مفقود!")

print("📌 USING DATABASE_URL =", DATABASE_URL)

# اتصال PostgreSQL
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False  # هنستخدم conn.commit() يدويًا
cursor = conn.cursor()   # عادي (tuples)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("EDU_BOT")

# ============================================================
#   FASTAPI APP
# ============================================================
app = FastAPI()
app.state.tg_application = None

# تقديم ملفات الـ PDF من /uploads تحت /files
app.mount(
    "/files",
    StaticFiles(directory=UPLOAD_DIR),
    name="files",
)

# ============================================================
#   USER STATE
# ============================================================
user_state: dict[int, dict] = {}

# ============================================================
#   KEYBOARD MAKER — RTL + أسماء فقط
# ============================================================
def make_keyboard(options):
    """
    options يمكن أن تكون:
      - tuples مثل: (id, name) أو (id, name, extra...)
      - أو (name,) فقط
      - أو strings جاهزة

    نحولها إلى:
      [ ['زر1', 'زر2'], ['زر3'], ['رجوع ↩️'] ]
    مع عكس أفقي (RTL) بحيث يكون أول خيار على اليمين.
    """
    labels: list[str] = []

    for opt in options:
        if isinstance(opt, (tuple, list)):
            if len(opt) >= 2:
                labels.append(str(opt[1]))   # نأخذ الاسم فقط
            elif len(opt) == 1:
                labels.append(str(opt[0]))
        else:
            labels.append(str(opt))

    labels = [lbl for lbl in labels if lbl.strip()]

    rows: list[list[str]] = []
    for i in range(0, len(labels), 2):
        row = labels[i:i + 2]
        row.reverse()   # عكس عشان يظهر أول عنصر على اليمين
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
        "مرحباً بكم ❤️\n\n"
        "📚 *اختر المرحلة للبدء:*"
    )

    cursor.execute("SELECT id, name FROM stages ORDER BY id")
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
    log.info(f"📩 USER CLICKED: {text} | STEP = {state.get('step')}")

    # ---------------- زر الرجوع ----------------
    if text == "رجوع ↩️":

        if state.get("step") == "subchild":
            state["step"] = "suboption"
            cursor.execute(
                "SELECT id, name FROM option_children WHERE option_id=%s",
                (state["option_id"],),
            )
            return await update.message.reply_text(
                "اختر القسم:", reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "suboption":
            state["step"] = "option"
            cursor.execute(
                """
                SELECT subject_options.id, subject_options.name
                FROM subject_option_map
                JOIN subject_options ON subject_options.id = subject_option_map.option_id
                WHERE subject_option_map.subject_id=%s
                """,
                (state["subject_id"],),
            )
            return await update.message.reply_text(
                "اختر نوع المحتوى:", reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "option":
            state["step"] = "subject"
            cursor.execute(
                "SELECT id, name FROM subjects WHERE grade_id=%s",
                (state["grade_id"],),
            )
            return await update.message.reply_text(
                "اختر المادة:", reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "subject":
            state["step"] = "grade"
            cursor.execute(
                "SELECT id, name FROM grades WHERE term_id=%s",
                (state["term_id"],),
            )
            return await update.message.reply_text(
                "اختر الصف:", reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "grade":
            state["step"] = "term"
            cursor.execute(
                "SELECT id, name FROM terms WHERE stage_id=%s",
                (state["stage_id"],),
            )
            return await update.message.reply_text(
                "اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "term":
            state["step"] = "stage"
            cursor.execute("SELECT id, name FROM stages ORDER BY id")
            return await update.message.reply_text(
                "اختر المرحلة:", reply_markup=make_keyboard(cursor.fetchall())
            )

        return await start(update, context)

    # ---------------- المرحلة ----------------
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=%s", (text,))
        row = cursor.fetchone()
        if not row:
            return
        state["stage_id"] = row[0]
        state["step"] = "term"
        cursor.execute(
            "SELECT id, name FROM terms WHERE stage_id=%s",
            (state["stage_id"],),
        )
        return await update.message.reply_text(
            "اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall())
        )

    # ---------------- الفصل ----------------
    if state["step"] == "term":
        cursor.execute(
            "SELECT id FROM terms WHERE name=%s AND stage_id=%s",
            (text, state["stage_id"]),
        )
        row = cursor.fetchone()
        if not row:
            return
        state["term_id"] = row[0]
        state["step"] = "grade"
        cursor.execute(
            "SELECT id, name FROM grades WHERE term_id=%s",
            (state["term_id"],),
        )
        return await update.message.reply_text(
            "اختر الصف:", reply_markup=make_keyboard(cursor.fetchall())
        )

    # ---------------- الصف ----------------
    if state["step"] == "grade":
        cursor.execute(
            "SELECT id FROM grades WHERE name=%s AND term_id=%s",
            (text, state["term_id"]),
        )
        row = cursor.fetchone()
        if not row:
            return
        state["grade_id"] = row[0]
        state["step"] = "subject"
        cursor.execute(
            "SELECT id, name FROM subjects WHERE grade_id=%s",
            (state["grade_id"],),
        )
        return await update.message.reply_text(
            "اختر المادة:", reply_markup=make_keyboard(cursor.fetchall())
        )

    # ---------------- المادة ----------------
    if state["step"] == "subject":
        cursor.execute(
            "SELECT id FROM subjects WHERE name=%s AND grade_id=%s",
            (text, state["grade_id"]),
        )
        row = cursor.fetchone()
        if not row:
            return
        state["subject_id"] = row[0]
        state["step"] = "option"
        cursor.execute(
            """
            SELECT subject_options.id, subject_options.name
            FROM subject_option_map
            JOIN subject_options ON subject_options.id = subject_option_map.option_id
            WHERE subject_option_map.subject_id=%s
            """,
            (state["subject_id"],),
        )
        return await update.message.reply_text(
            "اختر نوع المحتوى:", reply_markup=make_keyboard(cursor.fetchall())
        )

    # ---------------- OPTION ----------------
    if state["step"] == "option":
        cursor.execute(
            "SELECT id FROM subject_options WHERE name=%s",
            (text,),
        )
        row = cursor.fetchone()
        if not row:
            return
        state["option_id"] = row[0]
        state["step"] = "suboption"
        cursor.execute(
            "SELECT id, name FROM option_children WHERE option_id=%s",
            (state["option_id"],),
        )
        return await update.message.reply_text(
            "اختر القسم:", reply_markup=make_keyboard(cursor.fetchall())
        )

    # ---------------- SUBOPTION ----------------
    if state["step"] == "suboption":
        cursor.execute(
            "SELECT id FROM option_children WHERE name=%s AND option_id=%s",
            (text, state["option_id"]),
        )
        row = cursor.fetchone()
        if not row:
            return
        state["child_id"] = row[0]

        cursor.execute(
            "SELECT id, name FROM option_subchildren WHERE child_id=%s",
            (state["child_id"],),
        )
        subs = cursor.fetchall()

        if subs:
            state["step"] = "subchild"
            return await update.message.reply_text(
                "اختر القسم الفرعي:", reply_markup=make_keyboard(subs)
            )

        # لو مفيش subchildren → روابط مباشرة
        cursor.execute(
            """
            SELECT title, url
            FROM resources
            WHERE stage_id=%s AND term_id=%s AND grade_id=%s
              AND subject_id=%s AND option_id=%s AND child_id=%s
              AND (subchild_id IS NULL OR subchild_id=0)
            """,
            (
                state["stage_id"],
                state["term_id"],
                state["grade_id"],
                state["subject_id"],
                state["option_id"],
                state["child_id"],
            ),
        )
        resources = cursor.fetchall()

        if not resources:
            return await update.message.reply_text("لا يوجد محتوى.")

        msg = "\n".join(f"▪️ <a href='{u}'>{t}</a>" for t, u in resources)
        return await update.message.reply_text(
            msg, parse_mode="HTML", disable_web_page_preview=True
        )

    # ---------------- SUBCHILD ----------------
    if state["step"] == "subchild":
        cursor.execute(
            "SELECT id FROM option_subchildren WHERE name=%s AND child_id=%s",
            (text, state["child_id"]),
        )
        row = cursor.fetchone()
        if not row:
            return
        subchild_id = row[0]

        cursor.execute(
            """
            SELECT title, url
            FROM resources
            WHERE stage_id=%s AND term_id=%s AND grade_id=%s
              AND subject_id=%s AND option_id=%s AND child_id=%s AND subchild_id=%s
            """,
            (
                state["stage_id"],
                state["term_id"],
                state["grade_id"],
                state["subject_id"],
                state["option_id"],
                state["child_id"],
                subchild_id,
            ),
        )
        resources = cursor.fetchall()

        if not resources:
            return await update.message.reply_text("لا يوجد محتوى.")

        msg = "\n".join(f"▪️ <a href='{u}'>{t}</a>" for t, u in resources)
        return await update.message.reply_text(
            msg, parse_mode="HTML", disable_web_page_preview=True
        )

# ============================================================
#   FASTAPI — TELEGRAM WEBHOOK (lifespan)
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 Initializing Telegram application...")
    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    app.state.tg_application = tg_app

    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")

    async with tg_app:
        await tg_app.start()
        log.info("✅ Telegram Application started")
        yield
        log.info("🛑 Stopping Telegram Application...")
        await tg_app.stop()
        log.info("✅ Telegram Application stopped")


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
#   ADMIN HELPERS
# ============================================================
def _fetch_all(query, params=()):
    cursor.execute(query, params)
    return cursor.fetchall()

# ============================================================
#   ADMIN PANEL PAGE
# ============================================================
@app.get("/admin", response_class=HTMLResponse)
def admin_form():
    stages      = _fetch_all("SELECT id, name FROM stages ORDER BY id")
    terms       = _fetch_all("SELECT id, name, stage_id FROM terms ORDER BY id")
    grades      = _fetch_all("SELECT id, name, term_id FROM grades ORDER BY id")
    subjects    = _fetch_all("SELECT id, name, grade_id FROM subjects ORDER BY id")
    options     = _fetch_all("SELECT id, name FROM subject_options ORDER BY id")
    children    = _fetch_all("SELECT id, name, option_id FROM option_children ORDER BY id")
    subchildren = _fetch_all("SELECT id, name, child_id FROM option_subchildren ORDER BY id")
    subj_opt_map= _fetch_all("SELECT subject_id, option_id FROM subject_option_map")

    resources = _fetch_all("""
        SELECT id, subject_id, option_id, child_id,
               title, url, subchild_id,
               stage_id, term_id, grade_id
        FROM resources ORDER BY id DESC LIMIT 200
    """)

    stage_map   = {s[0]: s[1] for s in stages}
    term_map    = {t[0]: t[1] for t in terms}
    grade_map   = {g[0]: g[1] for g in grades}
    subject_map = {s[0]: s[1] for s in subjects}
    option_map  = {o[0]: o[1] for o in options}
    child_map   = {c[0]: c[1] for c in children}
    sub_map     = {sc[0]: sc[1] for sc in subchildren}

    rows = ""
    for r in resources:
        rid, sub_id, opt_id, child_id, title, url, subchild, stage_id, term_id, grade_id = r

        rows += f"""
        <tr>
            <td>{rid}</td>
            <td>{stage_map.get(stage_id,'')}</td>
            <td>{term_map.get(term_id,'')}</td>
            <td>{grade_map.get(grade_id,'')}</td>
            <td>{subject_map.get(sub_id,'')}</td>
            <td>{option_map.get(opt_id,'')}</td>
            <td>{child_map.get(child_id,'')}</td>
            <td>{sub_map.get(subchild,'') if subchild else ''}</td>
            <td>{title}</td>
            <td><a href='{url}' target='_blank'>فتح</a></td>
            <td><a class='btn btn-warning btn-sm' href='/admin/edit/{rid}'>تعديل</a></td>
            <td>
                <form method='post' action='/admin/delete/{rid}'
                    onsubmit="return confirm('حذف؟');">
                    <button class='btn btn-danger btn-sm'>حذف</button>
                </form>
            </td>
        </tr>
        """

    stages_json      = [{"id": s[0], "name": s[1]} for s in stages]
    terms_json       = [{"id": t[0], "name": t[1], "stage_id": t[2]} for t in terms]
    grades_json      = [{"id": g[0], "name": g[1], "term_id": g[2]} for g in grades]
    subjects_json    = [{"id": s[0], "name": s[1], "grade_id": s[2]} for s in subjects]
    options_json     = [{"id": o[0], "name": o[1]} for o in options]
    children_json    = [{"id": c[0], "name": c[1], "option_id": c[2]} for c in children]
    subchildren_json = [{"id": sc[0], "name": sc[1], "child_id": sc[2]} for sc in subchildren]
    subj_opt_map_json= [{"subject_id": m[0], "option_id": m[1]} for m in subj_opt_map]

    html = open("admin_template.html", "r", encoding="utf-8").read()
    html = (
        html.replace("__ROWS__", rows)
            .replace("__STAGES__", json.dumps(stages_json, ensure_ascii=False))
            .replace("__TERMS__", json.dumps(terms_json, ensure_ascii=False))
            .replace("__GRADES__", json.dumps(grades_json, ensure_ascii=False))
            .replace("__SUBJECTS__", json.dumps(subjects_json, ensure_ascii=False))
            .replace("__OPTIONS__", json.dumps(options_json, ensure_ascii=False))
            .replace("__CHILDREN__", json.dumps(children_json, ensure_ascii=False))
            .replace("__SUBCHILDREN__", json.dumps(subchildren_json, ensure_ascii=False))
            .replace("__SUBJOPT__", json.dumps(subj_opt_map_json, ensure_ascii=False))
    )

    return HTMLResponse(html)

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
    file: UploadFile | None = File(None),
):
    if password != ADMIN_PASSWORD:
        return HTMLResponse("❌ كلمة المرور غلط", status_code=401)

    subchild_val = int(subchild_id) if subchild_id.strip() else None
    final_url = url.strip()

    if file and file.filename:
        save_path = os.path.join(UPLOAD_DIR, file.filename)

        if os.path.isdir(save_path):
            return HTMLResponse("❌ اسم الملف غير صالح", status_code=400)

        with open(save_path, "wb") as f:
            f.write(await file.read())

        final_url = f"{APP_URL}/files/{file.filename}"

    if not final_url:
        return HTMLResponse("❌ يجب إضافة رابط أو PDF", status_code=400)

    # منع التكرار: نستخدم COALESCE لمقارنة subchild_id (NULL أو رقم)
    cursor.execute(
        """
        SELECT id FROM resources
        WHERE stage_id=%s AND term_id=%s AND grade_id=%s
          AND subject_id=%s AND option_id=%s AND child_id=%s
          AND COALESCE(subchild_id, 0) = COALESCE(%s, 0)
          AND title=%s
        """,
        (
            stage_id, term_id, grade_id,
            subject_id, option_id, child_id,
            subchild_val,
            title,
        ),
    )
    row = cursor.fetchone()

    if row:
        rid = row[0]
        return HTMLResponse(f"""
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
        """)

    cursor.execute("""
        INSERT INTO resources (
            subject_id, option_id, child_id,
            title, url, subchild_id,
            stage_id, term_id, grade_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        subject_id, option_id, child_id,
        title, final_url, subchild_val,
        stage_id, term_id, grade_id,
    ))
    conn.commit()

    return RedirectResponse("/admin", status_code=303)

# ============================================================
#   DELETE
# ============================================================
@app.post("/admin/delete/{rid}")
def delete_resource(rid: int):
    cursor.execute("DELETE FROM resources WHERE id=%s", (rid,))
    conn.commit()
    return RedirectResponse("/admin", status_code=303)

# ============================================================
#   EDIT PAGE
# ============================================================
@app.get("/admin/edit/{rid}", response_class=HTMLResponse)
def admin_edit_page(rid: int):
    cursor.execute("SELECT title, url FROM resources WHERE id=%s", (rid,))
    row = cursor.fetchone()

    if not row:
        return HTMLResponse("❌ غير موجود", status_code=404)

    title, url = row

    return HTMLResponse(f"""
        <html dir='rtl'>
        <head>
            <meta charset="utf-8">
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body class='p-3'>
        <h3>تعديل الرابط {rid}</h3>

        <form method="post" enctype="multipart/form-data">
            <label class="form-label">العنوان</label>
            <input name="title" class="form-control" value="{title}">

            <label class="form-label mt-2">الرابط</label>
            <input name="url" class="form-control" value="{url or ''}">

            <label class="form-label mt-2">PDF جديد (اختياري)</label>
            <input type="file" name="file" accept=".pdf" class="form-control">

            <button class="btn btn-success mt-3">حفظ</button>
        </form>

        <a href="/admin" class="btn btn-secondary mt-3">رجوع</a>
        </body></html>
    """)

# ============================================================
#   EDIT SAVE
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
        save_path = os.path.join(UPLOAD_DIR, file.filename)

        if os.path.isdir(save_path):
            return HTMLResponse("❌ اسم الملف غير صالح", status_code=400)

        with open(save_path, "wb") as f:
            f.write(await file.read())

        final_url = f"{APP_URL}/files/{file.filename}"

    cursor.execute(
        "UPDATE resources SET title=%s, url=%s WHERE id=%s",
        (title, final_url, rid),
    )
    conn.commit()

    return RedirectResponse("/admin", status_code=303)
