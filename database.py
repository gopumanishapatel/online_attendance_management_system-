import sqlite3
from datetime import date

DB_NAME = "attendance.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_no TEXT UNIQUE NOT NULL,
            department TEXT,
            year TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            attendance_date TEXT,
            status TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    """)

    conn.commit()
    conn.close()


def add_student(name, roll_no, department, year):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO students(name, roll_no, department, year)
            VALUES (?, ?, ?, ?)
        """, (name, roll_no, department, year))

        conn.commit()
        result = True

    except sqlite3.IntegrityError:
        result = False

    conn.close()
    return result


def get_students():
    conn = get_connection()

    query = """
        SELECT id, name, roll_no, department, year
        FROM students
        ORDER BY roll_no
    """

    import pandas as pd
    df = pd.read_sql_query(query, conn)

    conn.close()
    return df


def mark_attendance(student_id, status):
    conn = get_connection()
    cursor = conn.cursor()

    today = str(date.today())

    cursor.execute("""
        SELECT id FROM attendance
        WHERE student_id = ? AND attendance_date = ?
    """, (student_id, today))

    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE attendance
            SET status = ?
            WHERE student_id = ? AND attendance_date = ?
        """, (status, student_id, today))
    else:
        cursor.execute("""
            INSERT INTO attendance
            (student_id, attendance_date, status)
            VALUES (?, ?, ?)
        """, (student_id, today, status))

    conn.commit()
    conn.close()


def get_attendance():
    conn = get_connection()

    query = """
        SELECT
            s.name,
            s.roll_no,
            s.department,
            a.attendance_date,
            a.status
        FROM attendance a
        JOIN students s
        ON a.student_id = s.id
        ORDER BY a.attendance_date DESC
    """

    import pandas as pd
    df = pd.read_sql_query(query, conn)

    conn.close()
    return df


def get_attendance_percentage():
    conn = get_connection()

    query = """
        SELECT
            s.name,
            s.roll_no,
            COUNT(a.id) AS total_days,
            SUM(CASE WHEN a.status = 'Present'
                THEN 1 ELSE 0 END) AS present_days
        FROM students s
        LEFT JOIN attendance a
        ON s.id = a.student_id
        GROUP BY s.id
    """

    import pandas as pd
    df = pd.read_sql_query(query, conn)

    df["attendance_percentage"] = (
        df["present_days"] / df["total_days"].replace(0, 1) * 100
    ).round(2)

    conn.close()

    return df