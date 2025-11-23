import sqlite3
import os

DB_PATH = "edu_bot_data.db"

# =========================================================
#  هنا القواميس (الدكشنري) الخاصة بكِ
# =========================================================

MENU_DATA = {
    "main": {
        "text": "منصة تعليمية لطلاب جميع المراحل\n\nمن فضلك اختر المرحلة:",
        "buttons": [["الثانوية", "المتوسطة", "الابتدائية"], ["روابط مهمة"]],
    },
    "الابتدائية": {"text": "📚 اختر الفصل:", "buttons": [["الفصل الثاني", "الفصل الأول "], ["رجوع"]]},
    "المتوسطة":   {"text": "📚 اختر الفصل:", "buttons": [["الفصل الثاني", "الفصل الأول"], ["رجوع"]]},
    "الثانوية":   {"text": "📚 اختر الفصل:", "buttons": [["الفصل الثاني", "الفصل الأول"], ["رجوع"]]},
    "الفصل الأول (ابتدائي)":  {"text": "📘 اختر الصف:", "buttons": [["الصف الثانى","الصف الأول"],["الصف الرابع","الصف الثالث"],["الصف الخامس"],["رجوع"]]},
    "الفصل الثاني (ابتدائي)": {"text": "📘 اختر الصف:", "buttons": [["الصف الثانى","الصف الأول"],["الصف الرابع","الصف الثالث"],["الصف الخامس"],["رجوع"]]},
    "الفصل الأول (متوسط)":  {"text": "📘 اختر الصف:", "buttons": [["الصف السابع","الصف السادس"],["الصف التاسع","الصف الثامن"],["رجوع"]]},
    "الفصل الثاني (متوسط)": {"text": "📘 اختر الصف:", "buttons": [["الصف السابع","الصف السادس"],["الصف التاسع","الصف الثامن"],["رجوع"]]},
    "الفصل الأول (الثانوية)":  {"text": "📗 اختر الصف/التخصص:", "buttons": [["عاشر"],["حادي عشر أدبي","حادي عشر علمي"],["ثاني عشر أدبي","ثاني عشر علمي"],["رجوع"]]},
    "الفصل الثاني (الثانوية)": {"text": "📗 اختر الصف/التخصص:", "buttons": [["عاشر"],["حادي عشر أدبي","حادي عشر علمي"],["ثاني عشر أدبي","ثاني عشر علمي"],["رجوع"]]},
    "روابط مهمة": {"text": "🔗 اختر الرابط:", "buttons": [["رابط ١","رابط ٢"],["رجوع"]]},
}

IMPORTANT_LINKS = {
    "رابط ١": "https://example.com/link1",
    "رابط ٢": "https://example.com/link2",
}

ALL_SUBJECT_LINKS = {
    "الابتدائية": {"الرياضيات":"...", "اللغة العربية":"...", "العلوم":"...", "اللغة الإنجليزية":"...", "التربية الإسلامية":"...", "الدراسات الاجتماعية":"..."},
    "المتوسطة":   {"الرياضيات":"...", "العلوم":"...", "اللغة الإنجليزية":"...", "اللغة العربية":"...", "الاجتماعيات":"..."},
    "الثانوية":   {"الفيزياء":"...", "الكيمياء":"...", "الأحياء":"...", "الرياضيات":"...", "اللغة العربية":"...", "اللغة الإنجليزية":"...", "الفلسفة":"...", "الإحصاء":"..."},
}

SUBJECT_OPTIONS = {
    "main": ["مذكرات", "اختبارات", "فيديوهات", "رجوع"],
    "مذكرات": ["مذكرات نيو", "مذكرات أخرى", "رجوع"],
    "مذكرات نيو": ["المذكرة الشاملة", "ملخصات", "رجوع"],
    "اختبارات": ["قصير أول", "قصير ثاني", "فاينال", "أوراق عمل", "رجوع"],
    "فيديوهات": ["مراجعة", "حل اختبارات", "رجوع"],
}

# =========================================================
#  وظائف تحويل البيانات إلى قاعدة البيانات
# =========================================================

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    return conn

def setup_database_structure():
    """Creates the menu table if it doesn't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_text TEXT NOT NULL,
            link_url TEXT,
            parent_menu_text TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def populate_database_from_dicts():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM menu_items")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='menu_items'")
    
    items_to_insert = []
    items_to_insert.append(("رجوع", None, "any"))
    items_to_insert.append(("main", None, "root"))

    for parent_menu_name, details in MENU_DATA.items():
        if parent_menu_name != "main":
             items_to_insert.append((parent_menu_name, None, "main"))

        for button_row in details.get("buttons", []):
            for button_text in button_row:
                if button_text != "رجوع":
                   items_to_insert.append((button_text, None, parent_menu_name))

    # Insert initial structure
    cursor.executemany("INSERT OR IGNORE INTO menu_items (menu_text, link_url, parent_menu_text) VALUES (?, ?, ?)", items_to_insert)

    # Update with actual links
    final_links_map = {**IMPORTANT_LINKS} # Start with important links
    
    # Add subject links
    for stage, subjects in ALL_SUBJECT_LINKS.items():
        final_links_map.update(subjects)

    # Add subject options links
    final_links_map.update({
        "المذكرة الشاملة": "https://example.com/full_note.pdf",
        "ملخصات": "https://example.com/summary_note.pdf",
        "قصير أول": "https://example.com/quiz1.pdf",
        "قصير ثاني": "https://example.com/quiz2.pdf",
        "فاينال": "https://example.com/final.pdf",
        "أوراق عمل": "https://example.com/work.pdf",
        "مراجعة": "https://example.com/videos-review",
        "حل اختبارات": "https://example.com/videos-solutions",
    })

    for text, url in final_links_map.items():
         cursor.execute("UPDATE menu_items SET link_url = ? WHERE menu_text = ?", (url, text))

    conn.commit()
    conn.close()
    print(f"Database '{DB_PATH}' populated with initial menu structure.")


if __name__ == "__main__":
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing {DB_PATH}")
        
    setup_database_structure() 
    populate_database_from_dicts()

