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
# توكن بسيط للتوثيق فى الكوكيز
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "super-secret-admin-token")

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
        if not row:
            return
        state["stage_id"] = row[0]
        state["step"] = "term"
        cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
        return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall()))

    # ---------------- الفصل ----------------
    if state["step"] == "term":
        cursor.execute("SELECT id FROM terms WHERE name=? AND stage_id=?", (text, state["stage_id"]))
        row = cursor.fetchone()
        if not row:
            return
        state["term_id"] = row[0]
        state["step"] = "grade"
        cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
        return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(cursor.fetchall()))

    # ---------------- الصف ----------------
    if state["step"] == "grade":
        cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return
        state["grade_id"] = row[0]
        state["step"] = "subject"
        cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
        return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(cursor.fetchall()))

    # ---------------- المادة ----------------
    if state["step"] == "subject":
        cursor.execute("SELECT id FROM subjects WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return
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
        if not row:
            return
        state["option_id"] = row[0]
        state["step"] = "suboption"
        cursor.execute("SELECT name FROM option_children WHERE option_id=?", (state["option_id"],))
        return await update.message.reply_text("اختر القسم:", reply_markup=make_keyboard(cursor.fetchall()))

    # ---------------- SUBOPTION ----------------
    if state["step"] == "suboption":

        cursor.execute("SELECT id FROM option_children WHERE name=? AND option_id=?", (text, state["option_id"]))
        row = cursor.fetchone()
        if not row:
            return
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
        if not row:
            return
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
#   DB HELPER
# ============================================================
def _fetch_all(query, params=()):
    cursor.execute(query, params)
    return cursor.fetchall()


# ============================================================
#   ADMIN AUTH (LOGIN / LOGOUT)
# ============================================================
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form():
    return """
    <html lang='ar' dir='rtl'>
    <head>
        <meta charset='utf-8'>
        <title>تسجيل دخول الأدمن</title>
        <style>
            body {
                font-family: sans-serif;
                background: #eef2f7;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
            }
            .box {
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(0,0,0,.1);
                width: 320px;
            }
            input {
                padding: 8px;
                width: 100%;
                margin-top: 4px;
                margin-bottom: 10px;
                border-radius: 8px;
                border: 1px solid #ccc;
            }
            button {
                padding: 10px 16px;
                background: #1976d2;
                color: white;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                width: 100%;
            }
        </style>
    </head>
    <body>
        <div class='box'>
            <h2>🔐 تسجيل دخول الأدمن</h2>
            <form method='post' action='/admin/login'>
                <label>كلمة المرور:</label>
                <input type='password' name='password' required>
                <button type='submit'>دخول</button>
            </form>
        </div>
    </body>
    </html>
    """


@app.post("/admin/login")
def admin_login(password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        return HTMLResponse("❌ كلمة المرور غير صحيحة", status_code=401)

    resp = RedirectResponse("/admin", status_code=303)
    # تخزين التوكن فى الكوكيز
    resp.set_cookie(
        "admin_token",
        ADMIN_TOKEN,
        httponly=True,
        secure=False,      # لو هتشغلي HTTPS عدّليها True
        samesite="lax",
    )
    return resp


@app.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie("admin_token")
    return resp


def _require_admin(request: Request) -> bool:
    token = request.cookies.get("admin_token")
    if token != ADMIN_TOKEN:
        return False
    return True


# ============================================================
#   ADMIN DASHBOARD (LIST + ADD + UPLOAD)
# ============================================================
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):

    if not _require_admin(request):
        return RedirectResponse("/admin/login", status_code=303)

    subjects = _fetch_all("SELECT id, name FROM subjects")
    options = _fetch_all("SELECT id, name FROM subject_options")
    children = _fetch_all("SELECT id, name FROM option_children")
    subchildren = _fetch_all("SELECT id, name FROM option_subchildren")

    # resources joined with names
    resources = _fetch_all("""
        SELECT
            r.id,
            r.title,
            r.url,
            s.name AS subject_name,
            o.name AS option_name,
            c.name AS child_name,
            sc.name AS subchild_name
        FROM resources r
        LEFT JOIN subjects s ON s.id = r.subject_id
        LEFT JOIN subject_options o ON o.id = r.option_id
        LEFT JOIN option_children c ON c.id = r.child_id
        LEFT JOIN option_subchildren sc ON sc.id = r.subchild_id
        ORDER BY r.id DESC
    """)

    def make_options(rows):
        return "".join([f"<option value='{r[0]}'>{r[1]}</option>" for r in rows])

    rows_html = ""
    for r in resources:
        res_id, title, url, s_name, o_name, c_name, sc_name = r
        rows_html += f"""
        <tr>
            <td>{res_id}</td>
            <td>{title}</td>
            <td><a href="{url}" target="_blank">افتح</a></td>
            <td>{s_name or ''}</td>
            <td>{o_name or ''}</td>
            <td>{c_name or ''}</td>
            <td>{sc_name or ''}</td>
            <td>
                <form method='get' action='/admin/edit/{res_id}' style='display:inline;'>
                    <button type='submit'>تعديل</button>
                </form>
                <form method='post' action='/admin/delete/{res_id}' style='display:inline;' onsubmit="return confirm('هل أنت متأكد من الحذف؟');">
                    <button type='submit' style='background:#d32f2f;'>مسح</button>
                </form>
            </td>
        </tr>
        """

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
            h1 {{
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .layout {{
                display: flex;
                gap: 20px;
                align-items: flex-start;
            }}
            .box {{
                background: white;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(0,0,0,.1);
            }}
            .col-form {{
                flex: 1;
            }}
            .col-table {{
                flex: 2;
                max-height: 80vh;
                overflow: auto;
            }}
            select, input {{
                padding: 8px;
                width: 100%;
                margin-top: 4px;
                margin-bottom: 10px;
                border-radius: 8px;
                border: 1px solid #ccc;
            }}
            button {{
                padding: 8px 12px;
                background: #1976d2;
                color: white;
                border: none;
                border-radius: 8px;
                cursor: pointer;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }}
            th, td {{
                border: 1px solid #ddd;
                padding: 6px 8px;
                text-align: center;
            }}
            th {{
                background: #f5f5f5;
                position: sticky;
                top: 0;
            }}
            a {{
                color: #1976d2;
                text-decoration: none;
            }}
        </style>
    </head>

    <body>
        <h1>
            <span>✨ لوحة تحكم نيو أكاديمي</span>
            <a href="/admin/logout"><button style="background:#555;">تسجيل خروج</button></a>
        </h1>

        <div class='layout'>

            <!-- عمود الإدخال -->
            <div class='box col-form'>
                <h2>➕ إضافة رابط جديد</h2>
                <form method='post' action='/admin/add'>
                    <label>العنوان:</label>
                    <input type='text' name='title' required>

                    <label>الرابط:</label>
                    <input type='url' name='url' required>

                    <label>المادة:</label>
                    <select name='subject_id' required>
                        {make_options(subjects)}
                    </select>

                    <label>نوع المحتوى:</label>
                    <select name='option_id' required>
                        {make_options(options)}
                    </select>

                    <label>القسم:</label>
                    <select name='child_id' required>
                        {make_options(children)}
                    </select>

                    <label>القسم الفرعي (اختياري):</label>
                    <select name='subchild_id'>
                        <option value=''>بدون</option>
                        {make_options(subchildren)}
                    </select>

                    <button type='submit'>حفظ الرابط</button>
                </form>

                <hr style="margin:20px 0;">

                <h2>📄 رفع PDF</h2>
                <form method='post' action='/admin/upload' enctype='multipart/form-data'>
                    <label>المادة:</label>
                    <select name='subject_id' required>
                        {make_options(subjects)}
                    </select>

                    <label>نوع المحتوى:</label>
                    <select name='option_id' required>
                        {make_options(options)}
                    </select>

                    <label>القسم:</label>
                    <select name='child_id' required>
                        {make_options(children)}
                    </select>

                    <label>القسم الفرعي (اختياري):</label>
                    <select name='subchild_id'>
                        <option value=''>بدون</option>
                        {make_options(subchildren)}
                    </select>

                    <label>ملف PDF:</label>
                    <input type='file' name='file' accept='.pdf' required>

                    <button type='submit'>رفع الملف</button>
                </form>
            </div>

            <!-- عمود الجدول -->
            <div class='box col-table'>
                <h2>📋 جميع الروابط المسجلة</h2>
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>العنوان</th>
                            <th>الرابط</th>
                            <th>المادة</th>
                            <th>النوع</th>
                            <th>القسم</th>
                            <th>القسم الفرعي</th>
                            <th>إجراءات</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """


# ============================================================
#   ADD LINK (POST)
# ============================================================
@app.post("/admin/add")
def admin_add(
    request: Request,
    title: str = Form(...),
    url: str = Form(...),
    subject_id: int = Form(...),
    option_id: int = Form(...),
    child_id: int = Form(...),
    subchild_id: str | None = Form(None),
):
    if not _require_admin(request):
        return RedirectResponse("/admin/login", status_code=303)

    # معالجة القيمة الفارغة
    if not subchild_id:
        subchild_id_val = None
    else:
        subchild_id_val = int(subchild_id)

    cursor.execute("""
        INSERT INTO resources (subject_id, option_id, child_id, subchild_id, title, url)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (subject_id, option_id, child_id, subchild_id_val, title, url))

    conn.commit()
    return RedirectResponse("/admin", status_code=303)


# ============================================================
#   PDF UPLOAD (POST)
# ============================================================
@app.post("/admin/upload")
async def admin_upload(
    request: Request,
    subject_id: int = Form(...),
    option_id: int = Form(...),
    child_id: int = Form(...),
    subchild_id: str | None = Form(None),
    file: UploadFile = File(...),
):
    if not _require_admin(request):
        return RedirectResponse("/admin/login", status_code=303)

    upload_dir = os.path.join(BASE_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    file_url = f"{APP_URL}/files/{file.filename}"

    if not subchild_id:
        subchild_id_val = None
    else:
        subchild_id_val = int(subchild_id)

    cursor.execute("""
        INSERT INTO resources (subject_id, option_id, child_id, subchild_id, title, url)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (subject_id, option_id, child_id, subchild_id_val, file.filename, file_url))

    conn.commit()
    return RedirectResponse("/admin", status_code=303)


# ============================================================
#   EDIT RESOURCE (GET FORM + POST SAVE)
# ============================================================
@app.get("/admin/edit/{res_id}", response_class=HTMLResponse)
def admin_edit_form(res_id: int, request: Request):
    if not _require_admin(request):
        return RedirectResponse("/admin/login", status_code=303)

    cursor.execute("""
        SELECT id, title, url, subject_id, option_id, child_id, subchild_id
        FROM resources WHERE id = ?
    """, (res_id,))
    row = cursor.fetchone()
    if not row:
        return HTMLResponse("لم يتم العثور على هذا السجل", status_code=404)

    _, title, url, subject_id, option_id, child_id, subchild_id = row

    subjects = _fetch_all("SELECT id, name FROM subjects")
    options = _fetch_all("SELECT id, name FROM subject_options")
    children = _fetch_all("SELECT id, name FROM option_children")
    subchildren = _fetch_all("SELECT id, name FROM option_subchildren")

    def make_options(rows, selected_id):
        html = ""
        for r in rows:
            sel = " selected" if r[0] == selected_id else ""
            html += f"<option value='{r[0]}'{sel}>{r[1]}</option>"
        return html

    subchild_selected = subchild_id if subchild_id is not None else 0

    return f"""
    <html lang='ar' dir='rtl'>
    <head>
        <meta charset='utf-8'>
        <title>تعديل رابط</title>
        <style>
            body {{
                font-family: sans-serif;
                background: #eef2f7;
                padding: 20px;
            }}
            .box {{
                background: white;
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(0,0,0,.1);
                max-width: 600px;
                margin: auto;
            }}
            select, input {{
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
            a {{
                text-decoration:none;
            }}
        </style>
    </head>
    <body>
        <div class='box'>
            <h2>📝 تعديل الرابط رقم {res_id}</h2>
            <form method='post' action='/admin/edit/{res_id}'>
                <label>العنوان:</label>
                <input type='text' name='title' value="{title}" required>

                <label>الرابط:</label>
                <input type='url' name='url' value="{url}" required>

                <label>المادة:</label>
                <select name='subject_id' required>
                    {make_options(subjects, subject_id)}
                </select>

                <label>نوع المحتوى:</label>
                <select name='option_id' required>
                    {make_options(options, option_id)}
                </select>

                <label>القسم:</label>
                <select name='child_id' required>
                    {make_options(children, child_id)}
                </select>

                <label>القسم الفرعي (اختياري):</label>
                <select name='subchild_id'>
                    <option value=''>بدون</option>
                    {make_options(subchildren, subchild_selected)}
                </select>

                <button type='submit'>حفظ التعديلات</button>
                <a href="/admin"><button type="button" style="background:#555;margin-right:10px;">رجوع للوحة التحكم</button></a>
            </form>
        </div>
    </body>
    </html>
    """


@app.post("/admin/edit/{res_id}")
def admin_edit_save(
    res_id: int,
    request: Request,
    title: str = Form(...),
    url: str = Form(...),
    subject_id: int = Form(...),
    option_id: int = Form(...),
    child_id: int = Form(...),
    subchild_id: str | None = Form(None),
):
    if not _require_admin(request):
        return RedirectResponse("/admin/login", status_code=303)

    if not subchild_id:
        subchild_id_val = None
    else:
        subchild_id_val = int(subchild_id)

    cursor.execute("""
        UPDATE resources
        SET subject_id = ?, option_id = ?, child_id = ?, subchild_id = ?, title = ?, url = ?
        WHERE id = ?
    """, (subject_id, option_id, child_id, subchild_id_val, title, url, res_id))

    conn.commit()
    return RedirectResponse("/admin", status_code=303)


# ============================================================
#   DELETE RESOURCE
# ============================================================
@app.post("/admin/delete/{res_id}")
def admin_delete(res_id: int, request: Request):
    if not _require_admin(request):
        return RedirectResponse("/admin/login", status_code=303)

    cursor.execute("DELETE FROM resources WHERE id = ?", (res_id,))
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
