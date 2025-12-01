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

# Use pathlib for robust path manipulation
BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = BASE_DIR / "edu_bot_data.db"
UPLOAD_DIR = BASE_DIR / "uploads"
TEMPLATE_DIR = BASE_DIR / "templates" # A good practice to have a templates dir

# Ensure essential directories exist on startup
UPLOAD_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR.mkdir(exist_ok=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("❌ BOT_TOKEN or APP_URL missing!")

# ============================================================
#   LOGGING SETUP
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
    """Establishes and returns a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Allow accessing columns by name (e.g., row['name'])
    return conn

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    log.info("Initializing database...")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # ... (all CREATE TABLE IF NOT EXISTS statements from previous version) ...
        # Stages Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)
        """)
        # Terms Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS terms (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, stage_id INTEGER NOT NULL, FOREIGN KEY (stage_id) REFERENCES stages (id))
        """)
        # Grades Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS grades (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, term_id INTEGER NOT NULL, FOREIGN KEY (term_id) REFERENCES terms (id))
        """)
        # Subjects Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, grade_id INTEGER NOT NULL, FOREIGN KEY (grade_id) REFERENCES grades (id))
        """)
        # Subject Options Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subject_options (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)
        """)
        # Subject-Option Mapping Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subject_option_map (subject_id INTEGER NOT NULL, option_id INTEGER NOT NULL, PRIMARY KEY (subject_id, option_id), FOREIGN KEY (subject_id) REFERENCES subjects (id), FOREIGN KEY (option_id) REFERENCES subject_options (id))
        """)
        # Option Children Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS option_children (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, option_id INTEGER NOT NULL, FOREIGN KEY (option_id) REFERENCES subject_options (id))
        """)
        # Option Sub-Children Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS option_subchildren (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, child_id INTEGER NOT NULL, FOREIGN KEY (child_id) REFERENCES option_children (id))
        """)
        # Resources Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, url TEXT NOT NULL,
            stage_id INTEGER, term_id INTEGER, grade_id INTEGER, subject_id INTEGER,
            option_id INTEGER, child_id INTEGER, subchild_id INTEGER,
            FOREIGN KEY (stage_id) REFERENCES stages (id), FOREIGN KEY (term_id) REFERENCES terms (id),
            FOREIGN KEY (grade_id) REFERENCES grades (id), FOREIGN KEY (subject_id) REFERENCES subjects (id),
            FOREIGN KEY (option_id) REFERENCES subject_options (id), FOREIGN KEY (child_id) REFERENCES option_children (id),
            FOREIGN KEY (subchild_id) REFERENCES option_subchildren (id)
        )
        """)
        conn.commit()
    log.info("Database initialized successfully.")

# Run DB initialization on startup
init_db()

# ============================================================
#   USER STATE MANAGEMENT
# ============================================================
user_state: Dict[int, Dict[str, Any]] = {}

# ============================================================
#   HELPER FUNCTIONS
# ============================================================
def make_keyboard(options: List[Tuple[str, ...] | str], add_back_button: bool = True) -> ReplyKeyboardMarkup:
    """Creates a right-to-left formatted reply keyboard."""
    rows = []
    for i in range(0, len(options), 2):
        row = [opt[0] if isinstance(opt, tuple) else opt for opt in options[i:i + 2]]
        row.reverse()  # RTL support
        rows.append(row)
    if add_back_button:
        rows.append(["رجوع ↩️"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def fetch_all(query: str, params: tuple = ()) -> List[sqlite3.Row]:
    """Executes a query and returns all results."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

def fetch_one(query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    """Executes a query and returns a single result."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()

async def save_uploaded_file(file: UploadFile) -> Optional[str]:
    """Saves an uploaded file with a unique name and returns its public URL."""
    if not file or not file.filename:
        return None
    
    try:
        file_extension = Path(file.filename).suffix
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        save_path = UPLOAD_DIR / unique_filename
        
        content = await file.read()
        save_path.write_bytes(content)
        
        log.info(f"File '{unique_filename}' saved successfully.")
        return f"{APP_URL}/files/{unique_filename}"
    except Exception as e:
        log.error(f"Failed to save file: {e}")
        return None

async def send_resources(update: Update, state: dict):
    """Fetches and sends resources based on the current user state."""
    log.info(f"Fetching resources for state: {state}")
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
            await update.message.reply_text("لا يوجد محتوى لهذا الاختيار.")
            return

        msg = "\n".join(f"▪️ <a href='{r['url']}'>{r['title']}</a>" for r in rows)
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        log.error(f"Error fetching resources: {e}")
        await update.message.reply_text("حدث خطأ أثناء جلب المحتوى. يرجى المحاولة مرة أخرى.")

# ============================================================
#   BOT COMMAND & MESSAGE HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    chat_id = update.effective_chat.id
    user_state[chat_id] = {"step": "stage"}
    stages = fetch_all("SELECT name FROM stages ORDER BY id")
    stage_names = [(s['name'],) for s in stages]
    await update.message.reply_text(
        "✨ *منصة نيو أكاديمي التعليمية* ✨\nاختر المرحلة:",
        reply_markup=make_keyboard(stage_names),
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main handler for user text messages."""
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if chat_id not in user_state:
        return await start(update, context)

    state = user_state[chat_id]

    try:
        # --- Handle "Back" button ---
        if text == "رجوع ↩️":
            # This dictionary defines the navigation logic for the "Back" button
            back_steps = {
                "subchild": ("suboption", "SELECT name FROM option_children WHERE option_id=?", (state["option_id"],), "اختر القسم:"),
                "suboption": ("option", "SELECT so.name FROM subject_option_map som JOIN subject_options so ON so.id = som.option_id WHERE som.subject_id=?", (state["subject_id"],), "اختر نوع المحتوى:"),
                "option": ("subject", "SELECT name FROM subjects WHERE grade_id=?", (state["grade_id"],), "اختر المادة:"),
                "subject": ("grade", "SELECT name FROM grades WHERE term_id=?", (state["term_id"],), "اختر الصف:"),
                "grade": ("term", "SELECT name FROM terms WHERE stage_id=?", (state["stage_id"],), "اختر الفصل:"),
                "term": ("stage", "SELECT name FROM stages ORDER BY id", (), "اختر المرحلة:"),
            }
            if state.get("step") in back_steps:
                new_step, query, params, message = back_steps[state["step"]]
                state["step"] = new_step
                options = fetch_all(query, params)
                await update.message.reply_text(message, reply_markup=make_keyboard(options))
            else:
                return await start(update, context)
            return

        # --- Handle state-based navigation ---
        step_handlers = {
            "stage": ("term", "SELECT id FROM stages WHERE name=?", "SELECT name FROM terms WHERE stage_id=?", "اختر الفصل:"),
            "term": ("grade", "SELECT id FROM terms WHERE name=? AND stage_id=?", "SELECT name FROM grades WHERE term_id=?", "اختر الصف:"),
            "grade": ("subject", "SELECT id FROM grades WHERE name=?", "SELECT name FROM subjects WHERE grade_id=?", "اختر المادة:"),
            "subject": ("option", "SELECT id FROM subjects WHERE name=?", "SELECT so.name FROM subject_option_map som JOIN subject_options so ON so.id = som.option_id WHERE som.subject_id=?", "اختر نوع المحتوى:"),
            "option": ("suboption", "SELECT id FROM subject_options WHERE name=?", "SELECT name FROM option_children WHERE option_id=?", "اختر القسم:"),
        }

        if state["step"] in step_handlers:
            next_step, id_query, options_query, message = step_handlers[state["step"]]
            
            # Find ID of the selected item
            id_params = (text, state[f"{state['step']}_id"]) if state["step"] in ["term", "suboption"] else (text,)
            row = fetch_one(id_query, id_params)
            if not row:
                await update.message.reply_text("خيار غير صالح. يرجى الاختيار من القائمة.")
                return

            # Update state
            state[f"{state['step']}_id"] = row['id']
            state["step"] = next_step

            # Fetch next level options
            options_params = (state[f"{next_step}_id"],) if next_step != "stage" else (state[f"{state['step']}_id"],)
            options = fetch_all(options_query, options_params)

            if options:
                await update.message.reply_text(message, reply_markup=make_keyboard(options))
            else:
                # No further options, so fetch resources
                await send_resources(update, state)
        
        # Handle final selection (subchild)
        if state.get("step") == "suboption":
            row = fetch_one("SELECT id FROM option_children WHERE name=? AND option_id=?", (text, state["option_id"]))
            if row:
                state["child_id"] = row['id']
                # Check for subchildren
                subchildren = fetch_all("SELECT name FROM option_subchildren WHERE child_id=?", (state["child_id"],))
                if subchildren:
                    state["step"] = "subchild"
                    await update.message.reply_text("اختر القسم الفرعي:", reply_markup=make_keyboard(subchildren))
                else:
                    await send_resources(update, state)

        if state.get("step") == "subchild":
            row = fetch_one("SELECT id FROM option_subchildren WHERE name=? AND child_id=?", (text, state["child_id"]))
            if row:
                state["subchild_id"] = row['id']
                await send_resources(update, state)

    except Exception as e:
        log.error(f"Error in handle_message for chat_id {chat_id}: {e}")
        await update.message.reply_text("حدث خطأ غير متوقع. يرجى بدء المحادثة مرة أخرى باستخدام /start.")
        if chat_id in user_state:
            del user_state[chat_id]


# ============================================================
#   FASTAPI APPLICATION & LIFESPAN
# ============================================================
app = FastAPI(title="Edu Bot API")
# Mount the 'uploads' directory to be served publicly
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    log.info("Starting Telegram Bot application...")
    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await tg_app.bot.set_webhook(url=f"{APP_URL}/telegram")
    app.state.tg_application = tg_app
    
    async with tg_app:
        await tg_app.start()
        yield
        await tg_app.stop()
    # --- Shutdown ---
    log.info("Application shutdown complete.")

app.router.lifespan_context = lifespan

# ============================================================
#   FASTAPI ROUTES
# ============================================================
@app.post("/telegram")
async def telegram_webhook(request: Request):
    """Receives updates from Telegram."""
    update = Update.de_json(await request.json(), app.state.tg_application.bot)
    await app.state.tg_application.process_update(update)
    return Response(status_code=200)

@app.get("/")
def root():
    return {"status": "running"}

# --- Admin Panel ---
@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    """Renders the admin panel page."""
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

        # Create maps for easy lookup when rendering the table
        maps = {
            "stage_map": {s['id']: s['name'] for s in data["stages"]},
            "term_map": {t['id']: t['name'] for t in data["terms"]},
            "grade_map": {g['id']: g['name'] for g in data["grades"]},
            "subject_map": {s['id']: s['name'] for s in data["subjects"]},
            "option_map": {o['id']: o['name'] for o in data["options"]},
            "child_map": {c['id']: c['name'] for c in data["children"]},
            "sub_map": {sc['id']: sc['name'] for sc in data["subchildren"]},
        }
        
        rows_html = ""
        for r in data["resources"]:
            rows_html += f"""
            <tr>
                <td>{r['id']}</td><td>{maps['stage_map'].get(r['stage_id'], '')}</td><td>{maps['term_map'].get(r['term_id'], '')}</td>
                <td>{maps['grade_map'].get(r['grade_id'], '')}</td><td>{maps['subject_map'].get(r['subject_id'], '')}</td>
                <td>{maps['option_map'].get(r['option_id'], '')}</td><td>{maps['child_map'].get(r['child_id'], '')}</td>
                <td>{maps['sub_map'].get(r['subchild_id'], '') if r['subchild_id'] else ''}</td>
                <td>{r['title']}</td><td><a href="{r['url']}" target="_blank">فتح</a></td>
                <td><a class="btn btn-warning btn-sm" href="/admin/edit/{r['id']}">تعديل</a></td>
                <td><form method="post" action="/admin/delete/{r['id']}" onsubmit="return confirm('حذف نهائي؟');"><button class="btn btn-danger btn-sm">🗑️</button></form></td>
            </tr>
            """
        
        # Read template and inject data
        template_path = BASE_DIR / "admin_template.html"
        if not template_path.exists():
            raise HTTPException(status_code=500, detail="Admin template not found.")
            
        html = template_path.read_text(encoding="utf-8")
        html = html.replace("__ROWS__", rows_html)
        for key, value in data.items():
            html = html.replace(f"__{key.upper()}__", json.dumps([dict(r) for r in value], ensure_ascii=False))

        return HTMLResponse(html)
    except Exception as e:
        log.error(f"Error rendering admin panel: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

# --- Admin Add/Edit/Delete Logic ---
@app.post("/admin/add")
async def admin_add(
    password: str = Form(...), stage_id: int = Form(...), term_id: int = Form(...),
    grade_id: int = Form(...), subject_id: int = Form(...), option_id: int = Form(...),
    child_id: int = Form(...), subchild_id: str = Form(""), title: str = Form(...),
    url: str = Form(""), file: UploadFile = File(None)
):
    """Adds a new resource."""
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Incorrect password")

    if url and file and file.filename:
        raise HTTPException(status_code=400, detail="Provide either a URL or a file, not both.")

    final_url = url.strip() or await save_uploaded_file(file)

    if not final_url:
        raise HTTPException(status_code=400, detail="A URL or a file must be provided.")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO resources (title, url, stage_id, term_id, grade_id, subject_id, option_id, child_id, subchild_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, final_url, stage_id, term_id, grade_id, subject_id, option_id, child_id, int(subchild_id) if subchild_id else None)
            )
            conn.commit()
        log.info(f"Resource '{title}' added successfully.")
        return RedirectResponse("/admin", status_code=303)
    except Exception as e:
        log.error(f"Database error on add: {e}")
        raise HTTPException(status_code=500, detail="Failed to add resource to database.")

@app.get("/admin/edit/{rid}", response_class=HTMLResponse)
def edit_page(rid: int):
    """Shows the form to edit a resource."""
    resource = fetch_one("SELECT * FROM resources WHERE id=?", (rid,))
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    
    return HTMLResponse(f"""
    <html dir="rtl"><head><meta charset="utf-8"><title>تعديل البيانات</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"></head>
    <body class="p-4"><h3 class="mb-3">✏️ تعديل الرابط رقم {rid}</h3>
    <form method="post" enctype="multipart/form-data">
        <label class="mt-2">العنوان:</label><input name="title" class="form-control" value="{resource['title']}">
        <label class="mt-3">الرابط (إن وجد):</label><input name="url" class="form-control" value="{resource['url'] or ''}">
        <label class="mt-3">رفع PDF جديد (اختياري):</label><input type="file" name="file" class="form-control" accept=".pdf">
        <button class="btn btn-success mt-4">💾 حفظ التعديلات</button>
    </form><a href="/admin" class="btn btn-secondary mt-3">⬅️ رجوع للوحة التحكم</a></body></html>
    """)

@app.post("/admin/edit/{rid}")
async def edit_save(rid: int, title: str = Form(...), url: str = Form(""), file: UploadFile = File(None)):
    """Saves the edited resource."""
    final_url = url.strip()
    if file and file.filename:
        # If a new file is uploaded, its URL overrides the old one
        file_url = await save_uploaded_file(file)
        if file_url:
            final_url = file_url
    
    if not final_url:
        raise HTTPException(status_code=400, detail="A URL or a file must be provided.")
        
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE resources SET title=?, url=? WHERE id=?", (title, final_url, rid))
            conn.commit()
        log.info(f"Resource ID {rid} updated successfully.")
        return RedirectResponse("/admin", status_code=303)
    except Exception as e:
        log.error(f"Database error on edit: {e}")
        raise HTTPException(status_code=500, detail="Failed to update resource.")

@app.post("/admin/delete/{rid}")
def admin_delete(rid: int, password: str = Form(...)):
    """Deletes a resource."""
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Incorrect password")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM resources WHERE id=?", (rid,))
            conn.commit()
        log.info(f"Resource ID {rid} deleted successfully.")
        return RedirectResponse("/admin", status_code=303)
    except Exception as e:
        log.error(f"Database error on delete: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete resource.")