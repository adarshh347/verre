import sqlite3
from pathlib import Path

DB_DIR = Path.home() / ".local" / "share" / "desktop-calendar-widget"
DB_PATH = DB_DIR / "events.db"


def get_connection():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT,
            description TEXT DEFAULT '',
            reminder_minutes INTEGER DEFAULT 10,
            notified INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            local_path TEXT DEFAULT '',
            repo_owner TEXT DEFAULT '',
            repo_name TEXT DEFAULT '',
            color TEXT DEFAULT '#b8bb26',
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            due_date TEXT,
            status TEXT DEFAULT 'todo',
            github_issue_number INTEGER,
            github_issue_url TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS progress_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    return conn


# ---------------------------------------------------------------- projects

def add_project(name, local_path="", repo_owner="", repo_name="", color="#b8bb26"):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO projects (name, local_path, repo_owner, repo_name, color) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, local_path, repo_owner, repo_name, color),
        )
    conn.close()
    return cur.lastrowid


def update_project(project_id, name, local_path, repo_owner, repo_name, color):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE projects SET name=?, local_path=?, repo_owner=?, repo_name=?, "
            "color=? WHERE id=?",
            (name, local_path, repo_owner, repo_name, color, project_id),
        )
    conn.close()


def delete_project(project_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    conn.close()


def get_projects():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    conn.close()
    return rows


def get_project(project_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    return row


# ------------------------------------------------------------------- tasks

def add_task(title, project_id=None, description="", due_date=None, status="todo"):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, project_id, description, due_date, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, project_id, description, due_date, status),
        )
    conn.close()
    return cur.lastrowid


def update_task(task_id, title, project_id, description, due_date, status):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE tasks SET title=?, project_id=?, description=?, due_date=?, "
            "status=?, updated_at=datetime('now') WHERE id=?",
            (title, project_id, description, due_date, status, task_id),
        )
    conn.close()


def set_task_github_issue(task_id, issue_number, issue_url):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE tasks SET github_issue_number=?, github_issue_url=?, "
            "updated_at=datetime('now') WHERE id=?",
            (issue_number, issue_url, task_id),
        )
    conn.close()


def set_task_status(task_id, status):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE tasks SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, task_id),
        )
    conn.close()


def delete_task(task_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.close()


def get_tasks_for_date(date):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE due_date=? ORDER BY status, title", (date,)
    ).fetchall()
    conn.close()
    return rows


def get_open_tasks(project_id=None):
    conn = get_connection()
    if project_id:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status != 'done' AND project_id=? "
            "ORDER BY due_date IS NULL, due_date",
            (project_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status != 'done' "
            "ORDER BY due_date IS NULL, due_date"
        ).fetchall()
    conn.close()
    return rows


def get_due_or_overdue_tasks(today_str, limit=5):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM tasks
        WHERE status != 'done' AND due_date IS NOT NULL AND due_date <= ?
        ORDER BY due_date
        LIMIT ?
        """,
        (today_str, limit),
    ).fetchall()
    conn.close()
    return rows


def get_dates_with_tasks(start_date, end_date):
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT due_date FROM tasks WHERE due_date BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchall()
    conn.close()
    return {row["due_date"] for row in rows}


# ------------------------------------------------------------- progress log

def add_progress_note(project_id, date, note):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO progress_log (project_id, date, note) VALUES (?, ?, ?)",
            (project_id, date, note),
        )
    conn.close()
    return cur.lastrowid


def delete_progress_note(note_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM progress_log WHERE id=?", (note_id,))
    conn.close()


def get_progress_for_date(date):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT progress_log.*, projects.name AS project_name, projects.color AS project_color
        FROM progress_log
        LEFT JOIN projects ON projects.id = progress_log.project_id
        WHERE progress_log.date=?
        ORDER BY progress_log.created_at
        """,
        (date,),
    ).fetchall()
    conn.close()
    return rows


def get_progress_for_project(project_id, limit=30):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM progress_log WHERE project_id=? ORDER BY date DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return rows


def get_dates_with_progress(start_date, end_date):
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT date FROM progress_log WHERE date BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchall()
    conn.close()
    return {row["date"] for row in rows}


def add_event(title, date, time, description="", reminder_minutes=10):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO events (title, date, time, description, reminder_minutes) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, date, time, description, reminder_minutes),
        )
    conn.close()
    return cur.lastrowid


def update_event(event_id, title, date, time, description, reminder_minutes):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE events SET title=?, date=?, time=?, description=?, "
            "reminder_minutes=?, notified=0 WHERE id=?",
            (title, date, time, description, reminder_minutes, event_id),
        )
    conn.close()


def delete_event(event_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.close()


def get_events_for_date(date):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM events WHERE date=? ORDER BY time IS NULL, time", (date,)
    ).fetchall()
    conn.close()
    return rows


def get_dates_with_events(start_date, end_date):
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT date FROM events WHERE date BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchall()
    conn.close()
    return {row["date"] for row in rows}


def get_upcoming_events(from_date, from_time, limit=5):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM events
        WHERE date > ? OR (date = ? AND (time IS NULL OR time >= ?))
        ORDER BY date, time IS NULL, time
        LIMIT ?
        """,
        (from_date, from_date, from_time, limit),
    ).fetchall()
    conn.close()
    return rows


def get_pending_reminders(now_date, now_datetime_str):
    """Events with a time set, not yet notified, whose reminder window has started."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM events
        WHERE notified = 0 AND time IS NOT NULL AND date = ?
        """,
        (now_date,),
    ).fetchall()
    conn.close()
    return rows


def mark_notified(event_id):
    conn = get_connection()
    with conn:
        conn.execute("UPDATE events SET notified=1 WHERE id=?", (event_id,))
    conn.close()
