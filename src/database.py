from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "attendai.db")
LEGACY_SUBJECT_ID = 1


def connect(db_path: str | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def _create_attendance_table(conn: sqlite3.Connection, table_name: str = "attendance") -> None:
    conn.execute(
        f"""CREATE TABLE {table_name} (
            student_id TEXT NOT NULL,
            subject_id INTEGER NOT NULL DEFAULT {LEGACY_SUBJECT_ID},
            name TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            attendance_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Present',
            PRIMARY KEY (student_id, subject_id, attendance_date)
        )"""
    )


def init_db(db_path: str | None = None) -> None:
    """Initialize the database and safely migrate the original date-only schema.

    Old attendance rows are retained under an inactive "General / Legacy" subject.
    New attendance is unique per student + subject + date, allowing several courses
    to record attendance for the same student on the same day.
    """
    with connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                enrolled_on TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_date TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS subjects (
                subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS subject_sessions (
                subject_id INTEGER NOT NULL,
                session_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (subject_id, session_date)
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO subjects(subject_id, name, code, active) VALUES (?, ?, ?, 0)",
            (LEGACY_SUBJECT_ID, "General / Legacy", "LEGACY"),
        )

        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='attendance'"
        ).fetchone()
        if not table_exists:
            _create_attendance_table(conn)
        else:
            columns = conn.execute("PRAGMA table_info(attendance)").fetchall()
            column_names = {row["name"] for row in columns}
            pk_columns = [row["name"] for row in sorted(columns, key=lambda row: row["pk"]) if row["pk"]]
            desired_pk = ["student_id", "subject_id", "attendance_date"]
            if "subject_id" not in column_names or pk_columns != desired_pk:
                conn.execute("DROP INDEX IF EXISTS idx_attendance_date")
                conn.execute("DROP INDEX IF EXISTS idx_attendance_subject_date")
                conn.execute("ALTER TABLE attendance RENAME TO attendance_before_subject_migration")
                _create_attendance_table(conn, "attendance")
                old_columns = {row["name"] for row in conn.execute("PRAGMA table_info(attendance_before_subject_migration)").fetchall()}
                old_subject_expr = "subject_id" if "subject_id" in old_columns else str(LEGACY_SUBJECT_ID)
                conn.execute(
                    f"""INSERT OR IGNORE INTO attendance
                        (student_id, subject_id, name, attendance_date, attendance_time, status)
                        SELECT student_id, {old_subject_expr}, name, attendance_date, attendance_time, status
                        FROM attendance_before_subject_migration"""
                )
                conn.execute("DROP TABLE attendance_before_subject_migration")

        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(attendance_date);
            CREATE INDEX IF NOT EXISTS idx_attendance_subject_date ON attendance(subject_id, attendance_date);
            CREATE INDEX IF NOT EXISTS idx_subject_sessions_date ON subject_sessions(session_date);
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_settings(setting_key, setting_value) VALUES (?, ?)",
            ("low_attendance_threshold", "75"),
        )
        # Give legacy dates a matching legacy-subject session so historic reports remain usable.
        conn.execute(
            "INSERT OR IGNORE INTO subject_sessions(subject_id, session_date) SELECT ?, session_date FROM sessions",
            (LEGACY_SUBJECT_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO subject_sessions(subject_id, session_date) SELECT subject_id, attendance_date FROM attendance"
        )


def create_subject(name: str, code: str, db_path: str | None = None) -> int:
    name = name.strip()
    code = code.strip().upper()
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO subjects(name, code, active) VALUES (?, ?, 1)",
            (name, code),
        )
        return int(cursor.lastrowid)


def get_subjects(db_path: str | None = None, active_only: bool = True) -> list[dict]:
    query = "SELECT subject_id, name, code, active, created_at FROM subjects"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY active DESC, name COLLATE NOCASE"
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(query).fetchall()]


def get_subject(subject_id: int | str, db_path: str | None = None, active_only: bool = False) -> dict | None:
    try:
        subject_id = int(subject_id)
    except (TypeError, ValueError):
        return None
    query = "SELECT subject_id, name, code, active, created_at FROM subjects WHERE subject_id = ?"
    params: list[object] = [subject_id]
    if active_only:
        query += " AND active = 1"
    with connect(db_path) as conn:
        row = conn.execute(query, params).fetchone()
    return dict(row) if row else None


def sync_student_profile(
    student_id: str,
    name: str,
    enrolled_on: str | None = None,
    email: str | None = None,
    db_path: str | None = None,
) -> None:
    day = enrolled_on or datetime.now().strftime("%Y-%m-%d")
    with connect(db_path) as conn:
        existing = conn.execute("SELECT email FROM students WHERE student_id = ?", (student_id,)).fetchone()
        chosen_email = email if email is not None else (existing["email"] if existing else "")
        conn.execute(
            """INSERT INTO students(student_id, name, email, enrolled_on, active)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(student_id) DO UPDATE SET
                   name = excluded.name,
                   email = CASE WHEN excluded.email <> '' THEN excluded.email ELSE students.email END,
                   active = 1""",
            (student_id, name, chosen_email or "", day),
        )


def update_student_email(student_id: str, email: str, db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE students SET email = ? WHERE student_id = ?", (email, student_id))


def deactivate_student(student_id: str, db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE students SET active = 0 WHERE student_id = ?", (student_id,))


def get_student_metadata(db_path: str | None = None, active_only: bool = False) -> list[dict]:
    query = "SELECT * FROM students"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY name COLLATE NOCASE"
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(query).fetchall()]


def record_session(session_date: str, db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO sessions(session_date) VALUES (?)", (session_date,))


def record_subject_session(subject_id: int | str, session_date: str, db_path: str | None = None) -> None:
    subject = get_subject(subject_id, db_path, active_only=True)
    if not subject:
        raise ValueError("Select an active subject before starting attendance.")
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subject_sessions(subject_id, session_date) VALUES (?, ?)",
            (int(subject_id), session_date),
        )
        conn.execute("INSERT OR IGNORE INTO sessions(session_date) VALUES (?)", (session_date,))


def get_session_dates(start_date: str | None = None, end_date: str | None = None, db_path: str | None = None) -> list[str]:
    query = "SELECT session_date FROM sessions WHERE 1=1"
    params: list[str] = []
    if start_date:
        query += " AND session_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND session_date <= ?"
        params.append(end_date)
    query += " ORDER BY session_date"
    with connect(db_path) as conn:
        return [row[0] for row in conn.execute(query, params).fetchall()]


def get_subject_session_rows(start_date: str | None = None, end_date: str | None = None, db_path: str | None = None, subject_id: int | str | None = None) -> list[dict]:
    query = """SELECT ss.subject_id, ss.session_date, s.name AS subject_name, s.code AS subject_code
               FROM subject_sessions ss JOIN subjects s ON s.subject_id = ss.subject_id
               WHERE 1=1"""
    params: list[object] = []
    if start_date:
        query += " AND ss.session_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND ss.session_date <= ?"
        params.append(end_date)
    if subject_id not in (None, "", "all"):
        query += " AND ss.subject_id = ?"
        params.append(int(subject_id))
    query += " ORDER BY ss.session_date, s.name COLLATE NOCASE"
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_subject_session_dates(subject_id: int | str, start_date: str | None = None, end_date: str | None = None, db_path: str | None = None) -> list[str]:
    return [row["session_date"] for row in get_subject_session_rows(start_date, end_date, db_path, subject_id)]


def insert_attendance_once(
    student_id: str,
    name: str,
    attendance_date: str,
    attendance_time: str,
    status: str = "Present",
    db_path: str | None = None,
    subject_id: int = LEGACY_SUBJECT_ID,
) -> bool:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subject_sessions(subject_id, session_date) VALUES (?, ?)",
            (int(subject_id), attendance_date),
        )
        conn.execute("INSERT OR IGNORE INTO sessions(session_date) VALUES (?)", (attendance_date,))
        cursor = conn.execute(
            """INSERT OR IGNORE INTO attendance
               (student_id, subject_id, name, attendance_date, attendance_time, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (student_id, int(subject_id), name, attendance_date, attendance_time, status),
        )
        return cursor.rowcount == 1


def import_legacy_attendance(row: dict, fallback_date: str | None = None, db_path: str | None = None) -> None:
    student_id = str(row.get("Student ID", "")).strip()
    name = str(row.get("Name", "")).strip()
    date_value = str(row.get("Date", "") or fallback_date or "").strip()
    time_value = str(row.get("Time", "")).strip() or "00:00:00"
    status = str(row.get("Status", "Present")).strip() or "Present"
    if not student_id or not name or len(date_value) != 10:
        return
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO sessions(session_date) VALUES (?)", (date_value,))
        conn.execute("INSERT OR IGNORE INTO subject_sessions(subject_id, session_date) VALUES (?, ?)", (LEGACY_SUBJECT_ID, date_value))
        conn.execute(
            """INSERT OR IGNORE INTO attendance
               (student_id, subject_id, name, attendance_date, attendance_time, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (student_id, LEGACY_SUBJECT_ID, name, date_value, time_value, status),
        )
        conn.execute(
            "UPDATE students SET enrolled_on = CASE WHEN enrolled_on > ? THEN ? ELSE enrolled_on END WHERE student_id = ?",
            (date_value, date_value, student_id),
        )


def get_attendance_rows(start_date: str | None = None, end_date: str | None = None, db_path: str | None = None, subject_id: int | str | None = None) -> list[dict]:
    query = """SELECT a.student_id AS 'Student ID', a.name AS 'Name',
                      a.attendance_date AS 'Date', a.attendance_time AS 'Time',
                      a.status AS 'Status', s.name AS 'Subject', s.code AS 'Subject Code',
                      a.subject_id AS 'Subject ID'
               FROM attendance a JOIN subjects s ON s.subject_id = a.subject_id
               WHERE 1=1"""
    params: list[object] = []
    if start_date:
        query += " AND a.attendance_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND a.attendance_date <= ?"
        params.append(end_date)
    if subject_id not in (None, "", "all"):
        query += " AND a.subject_id = ?"
        params.append(int(subject_id))
    query += " ORDER BY a.attendance_date DESC, a.attendance_time DESC, s.name COLLATE NOCASE, a.name COLLATE NOCASE"
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_attendance_for_student(student_id: str, db_path: str | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(
            """SELECT a.attendance_date, a.attendance_time, a.status, a.subject_id, s.name AS subject_name
               FROM attendance a JOIN subjects s ON s.subject_id=a.subject_id
               WHERE a.student_id = ? ORDER BY a.attendance_date, s.name""", (student_id,)
        ).fetchall()]


def get_setting(key: str, default: str = "", db_path: str | None = None) -> str:
    with connect(db_path) as conn:
        row = conn.execute("SELECT setting_value FROM app_settings WHERE setting_key = ?", (key,)).fetchone()
    return str(row[0]) if row else default


def set_setting(key: str, value: str, db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO app_settings(setting_key, setting_value) VALUES (?, ?)
               ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value""",
            (key, value),
        )


def session_count(db_path: str | None = None) -> int:
    with connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM subject_sessions").fetchone()[0])


def student_email(student_id: str, db_path: str | None = None) -> str:
    with connect(db_path) as conn:
        row = conn.execute("SELECT email FROM students WHERE student_id = ?", (student_id,)).fetchone()
    return str(row[0] or "") if row else ""
