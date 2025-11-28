# ============================================================
#   IMPORTS & PATHS
# ============================================================
import os
import sqlite3
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Form
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

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("BOT")

user_state = {}

# باسورد الأدمن للوحة التحكم
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")


# ============================================================
#   KEYBOARD MAKER — RTL (Right → Left)
# ============================================================
def make_keyboard(options):
    rows = []

    for i in range(0, len(options), 2):
        row = [
            opt[0] if isinstance(opt, tuple) else opt
            for opt in options[i:i + 2]
        ]
        row.reverse()  # قلب الاتجاه يمين/يسار
        rows.append(row)

    rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ============================================================
#   /start COMMAND
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}

    welcome = (
        "✨ *منصة نيو أكاديمي التعليمية* ✨\n"
        "مرحباً بكم في منصتكم التعليمية المتكاملة ❤️\n\n"
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
#   MAIN TELEGRAM HANDLER
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    text = update.message.text

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]
    log.info(f"📩 USER CLICKED: {text}")

    # --------------------------------------------------------
    #   زر الرجوع ↩️
    # --------------------------------------------------------
    if text == "رجوع ↩️":

        if state.get("step") == "subchild":
            state["step"] = "suboption"
            cursor.execute(
                "SELECT name FROM option_children WHERE option_id=?",
                (state["option_id"],)
            )
            return await update.message.reply_text(
                "اختر القسم:",
                reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "suboption":
            state["step"] = "option"
            cursor.execute(
                """
                SELECT subject_options.name
                FROM subject_option_map
                JOIN subject_options 
                    ON subject_options.id = subject_option_map.option_id
                WHERE subject_option_map.subject_id=?
                """,
                (state["subject_id"],)
            )
            return await update.message.reply_text(
                "اختر نوع المحتوى:",
                reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "option":
            state["step"] = "subject"
            cursor.execute(
                "SELECT name FROM subjects WHERE grade_id=?",
                (state["grade_id"],)
            )
            return await update.message.reply_text(
                "اختر المادة:",
                reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "subject":
            state["step"] = "grade"
            cursor.execute(
                "SELECT name FROM grades WHERE term_id=?",
                (state["term_id"],)
            )
            return await update.message.reply_text(
                "اختر الصف:",
                reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "grade":
            state["step"] = "term"
            cursor.execute(
                "SELECT name FROM terms WHERE stage_id=?",
                (state["stage_id"],)
            )
            return await update.message.reply_text(
                "اختر الفصل:",
                reply_markup=make_keyboard(cursor.fetchall())
            )

        if state.get("step") == "term":
            state["step"] = "stage"
            cursor.execute("SELECT name FROM stages ORDER BY id")
            return await update.message.reply_text(
                "اختر المرحلة:",
                reply_markup=make_keyboard(cursor.fetchall())
            )

        # لو لأي سبب الستيت ملخبطة نرجعه للبداية
        return await start(update, context)

    # --------------------------------------------------------
    #   المرحلة
    # --------------------------------------------------------
    if state["step"] == "stage":
        cursor.execute("SELECT id FROM stages WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["stage_id"] = row[0]
        state["step"] = "term"

        cursor.execute(
            "SELECT name FROM terms WHERE stage_id=?",
            (state["stage_id"],)
        )
        return await update.message.reply_text(
            "اختر الفصل:",
            reply_markup=make_keyboard(cursor.fetchall())
        )

    # --------------------------------------------------------
    #   الفصل
    # --------------------------------------------------------
    if state["step"] == "term":
        cursor.execute(
            "SELECT id FROM terms WHERE name=? AND stage_id=?",
            (text, state["stage_id"])
        )
        row = cursor.fetchone()
        if not row:
            return

        state["term_id"] = row[0]
        state["step"] = "grade"

        cursor.execute(
            "SELECT name FROM grades WHERE term_id=?",
            (state["term_id"],)
        )
        return await update.message.reply_text(
            "اختر الصف:",
            reply_markup=make_keyboard(cursor.fetchall())
        )

    # --------------------------------------------------------
    #   الصف
    # --------------------------------------------------------
    if state["step"] == "grade":
        cursor.execute("SELECT id FROM grades WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["grade_id"] = row[0]
        state["step"] = "subject"

        cursor.execute(
            "SELECT name FROM subjects WHERE grade_id=?",
            (state["grade_id"],)
        )
        return await update.message.reply_text(
            "اختر المادة:",
            reply_markup=make_keyboard(cursor.fetchall())
        )

    # --------------------------------------------------------
    #   المادة
    # --------------------------------------------------------
    if state["step"] == "subject":
        cursor.execute("SELECT id FROM subjects WHERE name=?", (text,))
        row = cursor.fetchone()
        if not row:
            return

        state["subject_id"] = row[0]
        state["step"] = "option"

        cursor.execute(
            """
            SELECT subject_options.name
            FROM subject_option_map
            JOIN subject_options 
                ON subject_options.id = subject_option_map.option_id
            WHERE subject_option_map.subject_id=?
            """,
            (state["subject_id"],)
        )

        return await update.message.reply_text(
            "اختر نوع المحتوى:",
            reply_markup=make_keyboard(cursor.fetchall())
        )

    # --------------------------------------------------------
    #   OPTION (مذكرات / اختبارات / فيديوهات)
    # --------------------------------------------------------
    if state["step"] == "option":

        cursor.execute(
            "SELECT id FROM subject_options WHERE name=?",
            (text,)
        )
        row = cursor.fetchone()
        if not row:
            return

        state["option_id"] = row[0]
        state["step"] = "suboption"

        cursor.execute(
            "SELECT name FROM option_children WHERE option_id=?",
            (state["option_id"],)
        )
        children = cursor.fetchall()

        label = "اختر نوع المذكرات:" if state["option_id"] == 1 else "اختر القسم:"
        return await update.message.reply_text(
            label,
            reply_markup=make_keyboard(children)
        )

    # --------------------------------------------------------
    #   SUBOPTION
    # --------------------------------------------------------
    if state["step"] == "suboption":

        option_id = state["option_id"]

        cursor.execute(
            "SELECT id FROM option_children WHERE name=? AND option_id=?",
            (text, option_id)
        )
        row = cursor.fetchone()
        if not row:
            return

        state["child_id"] = row[0]

        cursor.execute(
            "SELECT name FROM option_subchildren WHERE child_id=?",
            (state["child_id"],)
        )
        subs = cursor.fetchall()

        # لو فيه subchildren (المذكرة الشاملة / ملخصات)
        if subs:
            state["step"] = "subchild"
            return await update.message.reply_text(
                "اختر القسم الفرعي:",
                reply_markup=make_keyboard(subs)
            )

        # لو مفيش subchildren → اعرض الروابط مباشرة
        cursor.execute(
            """
            SELECT title, url
            FROM resources
            WHERE subject_id=? AND option_id=? AND child_id=?
                  AND (subchild_id IS NULL OR subchild_id=0)
            """,
            (state["subject_id"], option_id, state["child_id"])
        )

        resources = cursor.fetchall()

        if not resources:
            return await update.message.reply_text(
                "لا يوجد محتوى حالياً.",
                reply_markup=make_keyboard([])
            )

        msg = "إليك المحتوى:\n\n" + "\n".join(
            f"▪️ <a href='{u}'>{t}</a>" for t, u in resources
        )

        return await update.message.reply_text(
            msg,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    # --------------------------------------------------------
    #   SUBCHILD (المذكرة الشاملة / ملخصات)
    # --------------------------------------------------------
    if state["step"] == "subchild":

        cursor.execute(
            """
            SELECT id FROM option_subchildren
            WHERE name=? AND child_id=?
            """,
            (text, state["child_id"])
        )
        row = cursor.fetchone()
        if not row:
            return

        subchild_id = row[0]

        cursor.execute(
            """
            SELECT title, url
            FROM resources
            WHERE subject_id=? AND option_id=? AND child_id=? AND subchild_id=?
            """,
            (state["subject_id"], state["option_id"], state["child_id"], subchild_id)
        )

        resources = cursor.fetchall()

        if not resources:
            return await update.message.reply_text(
                "لا يوجد محتوى حالياً.",
                reply_markup=make_keyboard([])
            )

        msg = "إليك المحتوى:\n\n" + "\n".join(
            f"▪️ <a href='{u}'>{t}</a>" for t, u in resources
        )

        return await update.message.reply_text(
            msg,
            parse_mode="HTML",
            disable_web_page_preview=True
        )


# ============================================================
#   FASTAPI APP & WEBHOOK
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
#   ADMIN DASHBOARD (WEB) — /admin
# ============================================================
def _fetch_all(query, params=()):
    cursor.execute(query, params)
    return cursor.fetchall()


@app.get("/admin", response_class=HTMLResponse)
def admin_form():
    subjects = _fetch_all("SELECT id, name FROM subjects ORDER BY id")
    options = _fetch_all("SELECT id, name FROM subject_options ORDER BY id")
    children = _fetch_all("SELECT id, name, option_id FROM option_children ORDER BY id")
    subchildren = _fetch_all("SELECT id, name, child_id FROM option_subchildren ORDER BY id")
    resources = _fetch_all(
        "SELECT id, title, url, subject_id, option_id, child_id, subchild_id FROM resources ORDER BY id DESC LIMIT 50"
    )

    html = f"""
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="utf-8" />
        <title>لوحة تحكم نيو أكاديمي</title>
        <style>
            body {{
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #f5f7fb;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 1100px;
                margin: 30px auto;
                background: #ffffff;
                padding: 24px 28px;
                border-radius: 16px;
                box-shadow: 0 12px 30px rgba(15, 23, 42, 0.12);
            }}
            h1 {{
                margin-top: 0;
                color: #1f2933;
                font-size: 26px;
            }}
            .subtitle {{
                color: #6b7280;
                margin-bottom: 20px;
            }}
            .card {{
                background: #f9fafb;
                border-radius: 12px;
                padding: 18px 20px;
                margin-bottom: 18px;
                border: 1px solid #e5e7eb;
            }}
            .card h2 {{
                margin-top: 0;
                font-size: 18px;
                color: #111827;
            }}
            label {{
                display: block;
                margin-top: 10px;
                margin-bottom: 4px;
                font-size: 14px;
                color: #374151;
            }}
            input[type="text"], input[type="url"], input[type="password"], input[type="number"] {{
                width: 100%;
                padding: 8px 10px;
                border-radius: 8px;
                border: 1px solid #d1d5db;
                font-size: 14px;
                box-sizing: border-box;
            }}
            input:focus {{
                outline: none;
                border-color: #2563eb;
                box-shadow: 0 0 0 1px rgba(37, 99, 235, .3);
            }}
            button {{
                margin-top: 14px;
                padding: 9px 18px;
                border-radius: 999px;
                border: none;
                cursor: pointer;
                font-size: 14px;
                font-weight: 600;
                background: linear-gradient(135deg, #2563eb, #4f46e5);
                color: white;
                box-shadow: 0 8px 20px rgba(37, 99, 235, .35);
            }}
            button:hover {{
                opacity: .92;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
                font-size: 13px;
            }}
            th, td {{
                border: 1px solid #e5e7eb;
                padding: 6px 8px;
                text-align: right;
            }}
            th {{
                background: #f3f4f6;
                font-weight: 600;
            }}
            .pill {{
                display: inline-block;
                padding: 2px 8px;
                border-radius: 999px;
                background: #e5e7eb;
                font-size: 11px;
                color: #374151;
            }}
            .small-note {{
                font-size: 12px;
                color: #6b7280;
                margin-top: 4px;
            }}
            a {{
                color: #2563eb;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
      <div class="container">
        <h1>لوحة تحكم نيو أكاديمي (Admin)</h1>
        <div class="subtitle">من هنا يمكنك إضافة الروابط وربطها بالمواد والخيارات المختلفة 👩‍🏫</div>

        <div class="card">
          <h2>➕ إضافة مورد جديد (Resource)</h2>
          <form method="post" action="/admin/add">
            <label>كلمة مرور الأدمن:</label>
            <input type="password" name="password" placeholder="ادخلي كلمة المرور (افتراضيًا: admin123)" required />

            <label>عنوان الملف (Title):</label>
            <input type="text" name="title" placeholder="مثال: مذكرة الرياضيات - الوحدة الأولى" required />

            <label>الرابط (URL):</label>
            <input type="url" name="url" placeholder="https://..." required />

            <label>ID المادة (subject_id):</label>
            <input type="number" name="subject_id" required />

            <label>ID نوع المحتوى (option_id) — مذكرات/اختبارات/فيديوهات:</label>
            <input type="number" name="option_id" required />

            <label>ID القسم (child_id) — مثل: مذكرات نيو / مذكرات أخرى / قصير أول ...:</label>
            <input type="number" name="child_id" required />

            <label>ID القسم الفرعي (subchild_id) — اختياري (اتركيه فارغ لو مفيش):</label>
            <input type="number" name="subchild_id" />

            <button type="submit">✅ حفظ المورد</button>
            <div class="small-note">استخدمي الجداول بالأسفل لمعرفة الأرقام (IDs) الصحيحة لكل مستوى.</div>
          </form>
        </div>

        <div class="card">
          <h2>📚 المواد (subjects)</h2>
          <table>
            <tr><th>ID</th><th>الاسم</th></tr>
            {''.join(f"<tr><td>{sid}</td><td>{name}</td></tr>" for sid, name in subjects)}
          </table>
        </div>

        <div class="card">
          <h2>🧩 أنواع المحتوى (subject_options)</h2>
          <table>
            <tr><th>ID</th><th>الاسم</th></tr>
            {''.join(f"<tr><td>{oid}</td><td>{name}</td></tr>" for oid, name in options)}
          </table>
        </div>

        <div class="card">
          <h2>📂 الأقسام (option_children)</h2>
          <table>
            <tr><th>ID</th><th>الاسم</th><th>option_id</th></tr>
            {''.join(f"<tr><td>{cid}</td><td>{name}</td><td>{opt_id}</td></tr>" for cid, name, opt_id in children)}
          </table>
        </div>

        <div class="card">
          <h2>📑 الأقسام الفرعية (option_subchildren)</h2>
          <table>
            <tr><th>ID</th><th>الاسم</th><th>child_id</th></tr>
            {''.join(f"<tr><td>{sid}</td><td>{name}</td><td>{child_id}</td></tr>" for sid, name, child_id in subchildren)}
          </table>
        </div>

        <div class="card">
          <h2>🔗 آخر 50 مورد مضاف (resources)</h2>
          <table>
            <tr>
              <th>ID</th>
              <th>العنوان</th>
              <th>الرابط</th>
              <th>subject_id</th>
              <th>option_id</th>
              <th>child_id</th>
              <th>subchild_id</th>
            </tr>
            {''.join(
                f"<tr><td>{rid}</td>"
                f"<td>{title}</td>"
                f"<td><a href='{url}' target='_blank'>فتح</a></td>"
                f"<td>{sid}</td><td>{oid}</td><td>{cid}</td><td>{scid}</td></tr>"
                for rid, title, url, sid, oid, cid, scid in resources
            )}
          </table>
        </div>

      </div>
    </body>
    </html>
    """
    return html


@app.post("/admin/add", response_class=HTMLResponse)
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
        return HTMLResponse(
            "<h3 style='font-family: sans-serif; direction: rtl;'>❌ كلمة المرور غير صحيحة</h3>"
            "<a href='/admin'>🔙 رجوع للوحة التحكم</a>",
            status_code=401,
        )

    # لو مفيش subchild_id نخليه NULL
    if subchild_id in ("", None):
        subchild_id_val = None
    else:
        subchild_id_val = subchild_id

    cursor.execute(
        """
        INSERT INTO resources (subject_id, option_id, child_id, subchild_id, title, url)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (subject_id, option_id, child_id, subchild_id_val, title, url),
    )
    conn.commit()

    return RedirectResponse("/admin", status_code=303)


# ============================================================
#   DEV SERVER (LOCAL)
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
