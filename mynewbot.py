# ============================================================
#   IMPORTS & PATHS
# ============================================================
import os
import sqlite3
import logging
from contextlib import asynccontextmanager
import json

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


# ----------------- Migration helper -----------------
def ensure_resources_columns():
    """
    تتأكد إن جدول resources فيه الأعمدة:
    stage_id, term_id, grade_id
    لو مش موجودة تضيفها تلقائيًا.
    """
    cursor.execute("PRAGMA table_info(resources)")
    cols = [row[1] for row in cursor.fetchall()]

    needed = {
        "stage_id": "INTEGER",
        "term_id": "INTEGER",
        "grade_id": "INTEGER",
    }

    for name, coltype in needed.items():
        if name not in cols:
            print(f"⚙️ Adding missing column {name} to resources table")
            cursor.execute(f"ALTER TABLE resources ADD COLUMN {name} {coltype}")

    conn.commit()


ensure_resources_columns()

# ============================================================
#   USER STATE
# ============================================================
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
        "مرحباً بكم ❤️\n\n"
        "📚 *اختر المرحلة للبدء:*"
    )

    cursor.execute("SELECT id, name FROM stages ORDER BY id")
    stages = cursor.fetchall()
    stage_names = [(s[1],) for s in stages]

    await update.message.reply_text(
        welcome,
        reply_markup=make_keyboard(stage_names),
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

        if state.get("step") == "subchild":
            state["step"] = "suboption"
            cursor.execute("SELECT name FROM option_children WHERE option_id=?", (state["option_id"],))
            return await update.message.reply_text("اختر القسم:", reply_markup=make_keyboard(cursor.fetchall()))

        if state.get("step") == "suboption":
            state["step"] = "option"
            cursor.execute("""
                SELECT subject_options.name
                FROM subject_option_map
                JOIN subject_options ON subject_options.id = subject_option_map.option_id
                WHERE subject_option_map.subject_id=?
            """, (state["subject_id"],))
            return await update.message.reply_text("اختر نوع المحتوى:", reply_markup=make_keyboard(cursor.fetchall()))

        if state.get("step") == "option":
            state["step"] = "subject"
            cursor.execute("SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],))
            return await update.message.reply_text("اختر المادة:", reply_markup=make_keyboard(cursor.fetchall()))

        if state.get("step") == "subject":
            state["step"] = "grade"
            cursor.execute("SELECT name FROM grades WHERE term_id=?", (state["term_id"],))
            return await update.message.reply_text("اختر الصف:", reply_markup=make_keyboard(cursor.fetchall()))

        if state.get("step") == "grade":
            state["step"] = "term"
            cursor.execute("SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],))
            return await update.message.reply_text("اختر الفصل:", reply_markup=make_keyboard(cursor.fetchall()))

        if state.get("step") == "term":
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

        # لو فيه أقسام فرعية
        if subs:
            state["step"] = "subchild"
            return await update.message.reply_text("اختر القسم الفرعي:", reply_markup=make_keyboard(subs))

        # لو مفيش أقسام فرعية → اعرض الروابط مباشرة
        cursor.execute("""
            SELECT title, url
            FROM resources
            WHERE stage_id=? AND term_id=? AND grade_id=?
              AND subject_id=? AND option_id=? AND child_id=?
              AND (subchild_id IS NULL OR subchild_id=0)
        """, (
            state["stage_id"],
            state["term_id"],
            state["grade_id"],
            state["subject_id"],
            state["option_id"],
            state["child_id"],
        ))

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
            WHERE stage_id=? AND term_id=? AND grade_id=?
              AND subject_id=? AND option_id=? AND child_id=? AND subchild_id=?
        """, (
            state["stage_id"],
            state["term_id"],
            state["grade_id"],
            state["subject_id"],
            state["option_id"],
            state["child_id"],
            subchild_id,
        ))

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
#   ADMIN HELPERS
# ============================================================
def _fetch_all(query, params=()):
    cursor.execute(query, params)
    return cursor.fetchall()

# ============================================================
#   ADMIN PANEL HTML (Bootstrap + Dynamic Dropdowns)
# ============================================================
@app.get("/admin", response_class=HTMLResponse)
def admin_form():
    # جلب البيانات الأساسية
    stages = _fetch_all("SELECT id, name FROM stages ORDER BY id")
    terms = _fetch_all("SELECT id, name, stage_id FROM terms ORDER BY id")
    grades = _fetch_all("SELECT id, name, term_id FROM grades ORDER BY id")
    subjects = _fetch_all("SELECT id, name, grade_id FROM subjects ORDER BY id")
    options = _fetch_all("SELECT id, name FROM subject_options ORDER BY id")
    children = _fetch_all("SELECT id, name, option_id FROM option_children ORDER BY id")
    subchildren = _fetch_all("SELECT id, name, child_id FROM option_subchildren ORDER BY id")
    subj_opt_map = _fetch_all("SELECT subject_id, option_id FROM subject_option_map")

    resources = _fetch_all("""
        SELECT id, title, url,
               stage_id, term_id, grade_id,
               subject_id, option_id, child_id, subchild_id
        FROM resources
        ORDER BY id DESC
        LIMIT 200
    """)

    # خرائط للأسماء
    stage_map = {s[0]: s[1] for s in stages}
    term_map = {t[0]: t[1] for t in terms}
    grade_map = {g[0]: g[1] for g in grades}
    subj_map = {s[0]: s[1] for s in subjects}
    opt_map = {o[0]: o[1] for o in options}
    child_map = {c[0]: c[1] for c in children}
    subchild_map = {sc[0]: sc[1] for sc in subchildren}

    # JSON منظم للدروب داون (ID + name + العلاقات)
    stages_js      = json.dumps([{"id": s[0], "name": s[1]} for s in stages], ensure_ascii=False)
    terms_js       = json.dumps([{"id": t[0], "name": t[1], "stage_id": t[2]} for t in terms], ensure_ascii=False)
    grades_js      = json.dumps([{"id": g[0], "name": g[1], "term_id": g[2]} for g in grades], ensure_ascii=False)
    subjects_js    = json.dumps([{"id": s[0], "name": s[1], "grade_id": s[2]} for s in subjects], ensure_ascii=False)
    options_js     = json.dumps([{"id": o[0], "name": o[1]} for o in options], ensure_ascii=False)
    children_js    = json.dumps([{"id": c[0], "name": c[1], "option_id": c[2]} for c in children], ensure_ascii=False)
    subchildren_js = json.dumps([{"id": sc[0], "name": sc[1], "child_id": sc[2]} for sc in subchildren], ensure_ascii=False)
    subj_opt_js    = json.dumps([{"subject_id": so[0], "option_id": so[1]} for so in subj_opt_map], ensure_ascii=False)

    # جدول الروابط
    rows_html = ""
    for r in resources:
        rid, title, url, st_id, term_id, grade_id, subj_id, opt_id, child_id, subc_id = r
        rows_html += (
            "<tr>"
            f"<td>{rid}</td>"
            f"<td>{stage_map.get(st_id, '')}</td>"
            f"<td>{term_map.get(term_id, '')}</td>"
            f"<td>{grade_map.get(grade_id, '')}</td>"
            f"<td>{subj_map.get(subj_id, '')}</td>"
            f"<td>{opt_map.get(opt_id, '')}</td>"
            f"<td>{child_map.get(child_id, '')}</td>"
            f"<td>{subchild_map.get(subc_id, '') if subc_id else ''}</td>"
            f"<td>{title}</td>"
            f"<td><a href=\"{url}\" target=\"_blank\">فتح</a></td>"
            f"<td><a class=\"btn btn-sm btn-warning\" href=\"/admin/edit/{rid}\">تعديل</a></td>"
            f"<td>"
            f"<form method=\"post\" action=\"/admin/delete/{rid}\" "
            f"onsubmit=\"return confirm('هل تريد الحذف؟');\">"
            f"<button class=\"btn btn-sm btn-danger\">حذف</button>"
            f"</form>"
            f"</td>"
            "</tr>"
        )

    # قالب HTML بدون f-string – هنستبدل العلامات بالأكواد
    html_template = """
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="utf-8">
        <title>لوحة تحكم نيو أكاديمي</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.rtl.min.css" rel="stylesheet">
        <style>
            body {
                background: linear-gradient(135deg, #eef2ff, #e0f7fa);
                min-height: 100vh;
            }
            .card {
                border-radius: 18px;
                box-shadow: 0 8px 20px rgba(0,0,0,0.08);
                border: none;
            }
            .main-title {
                font-weight: 800;
                color: #1e293b;
            }
            .badge-nano {
                background: #0ea5e9;
                color: #fff;
                border-radius: 999px;
                padding: 3px 10px;
                font-size: 0.75rem;
            }
            .table thead th {
                background: #f1f5f9 !important;
                font-weight: 600;
            }
        </style>
    </head>

    <body class="p-3">

        <div class="container-fluid">
            <div class="text-center mb-4">
                <h1 class="main-title">✨ لوحة تحكم نيو أكاديمي ✨</h1>
                <span class="badge-nano mt-2">إدارة الروابط وملفات PDF للمنصة</span>
            </div>

            <div class="row g-4">
                <!-- فورم الإضافة -->
                <div class="col-lg-5">
                    <div class="card p-3">
                        <h4 class="mb-3">➕ إضافة رابط / PDF جديد</h4>

                        <form method="post" action="/admin/add" enctype="multipart/form-data">

                            <div class="mb-2">
                                <label class="form-label">كلمة المرور:</label>
                                <input type="password" name="password" class="form-control" required>
                            </div>

                            <div class="row g-2 mt-1">
                                <div class="col-6">
                                    <label class="form-label">المرحلة</label>
                                    <select id="stage" name="stage_id" class="form-select" required></select>
                                </div>
                                <div class="col-6">
                                    <label class="form-label">الفصل</label>
                                    <select id="term" name="term_id" class="form-select" required></select>
                                </div>
                                <div class="col-6">
                                    <label class="form-label">الصف</label>
                                    <select id="grade" name="grade_id" class="form-select" required></select>
                                </div>
                                <div class="col-6">
                                    <label class="form-label">المادة</label>
                                    <select id="subject" name="subject_id" class="form-select" required></select>
                                </div>
                                <div class="col-6">
                                    <label class="form-label">نوع المحتوى</label>
                                    <select id="option" name="option_id" class="form-select" required></select>
                                </div>
                                <div class="col-6">
                                    <label class="form-label">القسم</label>
                                    <select id="child" name="child_id" class="form-select" required></select>
                                </div>
                                <div class="col-12">
                                    <label class="form-label">القسم الفرعي (اختياري)</label>
                                    <select id="subchild" name="subchild_id" class="form-select">
                                        <option value="">لا يوجد</option>
                                    </select>
                                </div>
                            </div>

                            <hr>

                            <div class="mb-2">
                                <label class="form-label">العنوان</label>
                                <input type="text" name="title" class="form-control" required>
                            </div>

                            <div class="mb-2">
                                <label class="form-label">الرابط (اختياري)</label>
                                <input type="url" name="url" class="form-control" placeholder="https://...">
                            </div>

                            <div class="mb-3">
                                <label class="form-label">ملف PDF (اختياري)</label>
                                <input type="file" name="file" accept=".pdf" class="form-control">
                            </div>

                            <button class="btn btn-primary w-100">💾 حفظ</button>
                        </form>
                    </div>
                </div>

                <!-- جدول الروابط -->
                <div class="col-lg-7">
                    <div class="card p-3">
                        <h4 class="mb-3">🔗 أحدث الروابط</h4>
                        <div class="table-responsive" style="max-height: 70vh; overflow:auto;">
                            <table class="table table-hover table-bordered align-middle">
                                <thead class="table-light">
                                    <tr>
                                        <th>ID</th>
                                        <th>المرحلة</th>
                                        <th>الفصل</th>
                                        <th>الصف</th>
                                        <th>المادة</th>
                                        <th>النوع</th>
                                        <th>القسم</th>
                                        <th>فرعي</th>
                                        <th>العنوان</th>
                                        <th>الرابط</th>
                                        <th>تعديل</th>
                                        <th>حذف</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    __ROWS__
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
    const stages      = __STAGES_JS__;
    const terms       = __TERMS_JS__;
    const grades      = __GRADES_JS__;
    const subjects    = __SUBJECTS_JS__;
    const options     = __OPTIONS_JS__;
    const children    = __CHILDREN_JS__;
    const subchildren = __SUBCHILDREN_JS__;
    const subjOptMap  = __SUBJOPT_JS__;

    function fill(sel, arr, placeholder) {
        sel.innerHTML = "";

        let first = document.createElement("option");
        first.value = "";
        first.textContent = placeholder;
        sel.appendChild(first);

        arr.forEach(function(item) {
            let opt = document.createElement("option");
            opt.value = item.id;
            opt.textContent = item.name;
            sel.appendChild(opt);
        });
    }

    let s  = document.getElementById("stage");
    let t  = document.getElementById("term");
    let g  = document.getElementById("grade");
    let sb = document.getElementById("subject");
    let op = document.getElementById("option");
    let ch = document.getElementById("child");
    let sc = document.getElementById("subchild");

    fill(s, stages, "اختر المرحلة");

    s.onchange = function () {
        let sid = parseInt(s.value || "0");

        fill(t, terms.filter(x => x.stage_id === sid), "اختر الفصل");
        fill(g, [], "اختر الصف");
        fill(sb, [], "اختر المادة");
        fill(op, [], "اختر النوع");
        fill(ch, [], "اختر القسم");
        sc.innerHTML = "<option value=''>لا يوجد</option>";
    };

    t.onchange = function () {
        let tid = parseInt(t.value || "0");

        fill(g, grades.filter(x => x.term_id === tid), "اختر الصف");
        fill(sb, [], "اختر المادة");
        fill(op, [], "اختر النوع");
        fill(ch, [], "اختر القسم");
        sc.innerHTML = "<option value=''>لا يوجد</option>";
    };

    g.onchange = function () {
        let gid = parseInt(g.value || "0");

        fill(sb, subjects.filter(x => x.grade_id === gid), "اختر المادة");
        fill(op, [], "اختر النوع");
        fill(ch, [], "اختر القسم");
        sc.innerHTML = "<option value=''>لا يوجد</option>";
    };

    sb.onchange = function () {
        let sid = parseInt(sb.value || "0");

        let allowed = subjOptMap
            .filter(x => x.subject_id === sid)
            .map(x => x.option_id);

        fill(op, options.filter(x => allowed.includes(x.id)), "اختر النوع");
        fill(ch, [], "اختر القسم");
        sc.innerHTML = "<option value=''>لا يوجد</option>";
    };

    op.onchange = function () {
        let oid = parseInt(op.value || "0");

        fill(ch, children.filter(x => x.option_id === oid), "اختر القسم");
        sc.innerHTML = "<option value=''>لا يوجد</option>";
    };

    ch.onchange = function () {
        let cid = parseInt(ch.value || "0");

        fill(sc, subchildren.filter(x => x.child_id === cid), "لا يوجد");
    };
</script>

    </body>
    </html>
    """


    html = (
        html_template
        .replace("__ROWS__", rows_html)
        .replace("__STAGES_JS__", stages_js)
        .replace("__TERMS_JS__", terms_js)
        .replace("__GRADES_JS__", grades_js)
        .replace("__SUBJECTS_JS__", subjects_js)
        .replace("__OPTIONS_JS__", options_js)
        .replace("__CHILDREN_JS__", children_js)
        .replace("__SUBCHILDREN_JS__", subchildren_js)
        .replace("__SUBJOPT_JS__", subj_opt_js)
    )

    return HTMLResponse(html)
@app.post("/admin/add")
async def admin_add(
    password: str = Form(...),
    stage_id: int = Form(...),
    term_id: int = Form(...),
    grade_id: int = Form(...),
    subject_id: int = Form(...),
    option_id: int = Form(...),
    child_id: int = Form(...),
    subchild_id: int | None = Form(None),
    title: str = Form(...),
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
):
    if password != ADMIN_PASSWORD:
        return HTMLResponse("❌ كلمة المرور غلط", status_code=401)

    final_url = url

    # لو فيه PDF
    if file:
        upload_dir = os.path.join(BASE_DIR, "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())

        final_url = f"{APP_URL}/files/{file.filename}"

    if not final_url:
        return HTMLResponse("❌ لازم تضيفي رابط أو PDF", status_code=400)

    cursor.execute("""
        INSERT INTO resources (
            stage_id, term_id, grade_id,
            subject_id, option_id, child_id, subchild_id,
            title, url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        stage_id, term_id, grade_id,
        subject_id, option_id, child_id, subchild_id,
        title, final_url
    ))
    conn.commit()

    return RedirectResponse("/admin", status_code=303)
@app.post("/admin/delete/{res_id}")
def admin_delete(res_id: int):
    cursor.execute("DELETE FROM resources WHERE id=?", (res_id,))
    conn.commit()
    return RedirectResponse("/admin", status_code=303)
@app.get("/admin/edit/{res_id}", response_class=HTMLResponse)
def edit_resource_page(res_id: int):
    cursor.execute("SELECT title, url FROM resources WHERE id=?", (res_id,))
    row = cursor.fetchone()

    if not row:
        return HTMLResponse("❌ الرابط غير موجود", status_code=404)

    title, url = row

    html = f"""
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="utf-8">
        <title>تعديل الرابط رقم {res_id}</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.rtl.min.css" rel="stylesheet">
    </head>

    <body class="p-3">
        <div class="container" style="max-width: 700px;">
            <div class="card p-4">
                <h3 class="mb-3">✏️ تعديل الرابط رقم {res_id}</h3>

                <form method="post" action="/admin/edit/{res_id}" enctype="multipart/form-data">

                    <div class="mb-3">
                        <label class="form-label">العنوان:</label>
                        <input type="text" name="title" class="form-control" value="{title}" required>
                    </div>

                    <div class="mb-3">
                        <label class="form-label">الرابط (URL):</label>
                        <input type="url" name="url" class="form-control" value="{url or ''}">
                    </div>

                    <div class="mb-3">
                        <label class="form-label">PDF جديد (اختياري):</label>
                        <input type="file" name="file" accept=".pdf" class="form-control">
                        <small class="text-muted">لو اخترت PDF جديد، سيتم استبدال الرابط الحالي برابط الملف.</small>
                    </div>

                    <button class="btn btn-success w-100">💾 حفظ التعديلات</button>
                </form>

                <a href="/admin" class="btn btn-secondary w-100 mt-3">⬅ رجوع للوحة التحكم</a>
            </div>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(html)
@app.post("/admin/edit/{res_id}")
async def edit_resource(
    res_id: int,
    title: str = Form(...),
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
):
    final_url = url

    if file:
        upload_dir = os.path.join(BASE_DIR, "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())

        final_url = f"{APP_URL}/files/{file.filename}"

    cursor.execute("""
        UPDATE resources
        SET title = ?, url = ?
        WHERE id = ?
    """, (title, final_url, res_id))
    conn.commit()

    return RedirectResponse("/admin", status_code=303)

