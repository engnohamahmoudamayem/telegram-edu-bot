-- ===========================
--   مراحل التعليم
-- ===========================
CREATE TABLE stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- ===========================
--   الفصول الدراسية
-- ===========================
CREATE TABLE terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY(stage_id) REFERENCES stages(id)
);

-- ===========================
--   الصفوف
-- ===========================
CREATE TABLE grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY(stage_id) REFERENCES stages(id)
);

-- ===========================
--   المواد لكل صف
-- ===========================
CREATE TABLE subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grade_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY(grade_id) REFERENCES grades(id)
);

-- ===========================
--   أنواع المحتوى (مذكرات – اختبارات – فيديوهات)
-- ===========================
CREATE TABLE content_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

-- ===========================
--   أنواع فرعية (مثل مذكرات نيو – قصير أول – مراجعة)
-- ===========================
CREATE TABLE content_subtypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY(type_id) REFERENCES content_types(id)
);

-- ===========================
--   الملفات النهائية (PDF – فيديو – رابط)
-- ===========================
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id INTEGER NOT NULL,
    term_id INTEGER NOT NULL,
    grade_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    type_id INTEGER NOT NULL,
    subtype_id INTEGER,
    title TEXT NOT NULL,
    file_url TEXT NOT NULL,

    FOREIGN KEY(stage_id) REFERENCES stages(id),
    FOREIGN KEY(term_id) REFERENCES terms(id),
    FOREIGN KEY(grade_id) REFERENCES grades(id),
    FOREIGN KEY(subject_id) REFERENCES subjects(id),
    FOREIGN KEY(type_id) REFERENCES content_types(id),
    FOREIGN KEY(subtype_id) REFERENCES content_subtypes(id)
);
