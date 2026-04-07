# db_manager.py
import sqlite3
import json
import time
import threading

DB_FILE = "exam_monitor.db"
_conn = None
_lock = threading.RLock()


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db():
    """Create all tables if they do not exist."""
    conn = _get_conn()
    with _lock:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS exam_sessions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id          TEXT UNIQUE NOT NULL,
                name             TEXT,
                duration_minutes INTEGER,
                state            TEXT    DEFAULT 'active',
                allowed_apps     TEXT    DEFAULT '[]',
                blocked_apps     TEXT    DEFAULT '[]',
                start_time       REAL,
                end_time         REAL,
                created_at       REAL
            );
            CREATE TABLE IF NOT EXISTS student_connections (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       INTEGER REFERENCES exam_sessions(id),
                student_id       TEXT NOT NULL,
                login_id         TEXT,
                ip               TEXT,
                hostname         TEXT,
                state            TEXT    DEFAULT 'in_progress',
                exam_id          TEXT,
                session_token    TEXT,
                time_left        INTEGER DEFAULT 0,
                connected_at     REAL,
                disconnected_at  REAL,
                total_risk_score INTEGER DEFAULT 0,
                risk_level       TEXT    DEFAULT 'TEMIZ'
            );
            CREATE TABLE IF NOT EXISTS monitoring_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER REFERENCES exam_sessions(id),
                student_id  TEXT,
                event_type  TEXT,
                event_data  TEXT    DEFAULT '{}',
                severity    TEXT    DEFAULT 'INFO',
                timestamp   REAL
            );
            CREATE TABLE IF NOT EXISTS violations (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id     INTEGER REFERENCES exam_sessions(id),
                student_id     TEXT,
                violation_type TEXT,
                window_name    TEXT,
                risk_score     INTEGER DEFAULT 0,
                risk_level     TEXT,
                open_apps      TEXT    DEFAULT '[]',
                timestamp      REAL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER REFERENCES exam_sessions(id),
                action     TEXT,
                actor      TEXT DEFAULT 'system',
                target     TEXT,
                details    TEXT DEFAULT '{}',
                result     TEXT DEFAULT 'OK',
                timestamp  REAL
            );
        """)
        conn.commit()


# ─── BACKWARD-COMPATIBLE FUNCTIONS ───────────────────────────────────────────

def save_server_state(active_students, exam_registry):
    """
    Save full server state snapshot to SQLite (crash recovery).
    Filters out live WebSocket objects before persisting.
    """
    conn = _get_conn()
    with _lock:
        # Upsert exam sessions
        for exam_id, payload in exam_registry.items():
            conn.execute(
                """INSERT INTO exam_sessions
                       (exam_id, name, duration_minutes, state,
                        allowed_apps, blocked_apps, created_at)
                   VALUES (?, ?, ?, 'active', ?, ?, ?)
                   ON CONFLICT(exam_id) DO UPDATE SET
                       name=excluded.name,
                       duration_minutes=excluded.duration_minutes,
                       allowed_apps=excluded.allowed_apps,
                       blocked_apps=excluded.blocked_apps""",
                (
                    exam_id,
                    payload.get("name", ""),
                    payload.get("duration_minutes", 40),
                    json.dumps(payload.get("allowed_apps", [])),
                    json.dumps(payload.get("blocked_apps", [])),
                    time.time(),
                ),
            )

        # Upsert student connections (drop live ws object)
        for sid, info in active_students.items():
            safe = {k: v for k, v in info.items() if k != "ws"}
            exam_id = safe.get("exam_id", "")

            row_s = conn.execute(
                "SELECT id FROM exam_sessions WHERE exam_id = ?", (exam_id,)
            ).fetchone()
            session_id = row_s["id"] if row_s else None

            row_sc = conn.execute(
                "SELECT id FROM student_connections WHERE student_id = ? AND exam_id = ?",
                (sid, exam_id),
            ).fetchone()

            if row_sc:
                conn.execute(
                    """UPDATE student_connections SET
                           state=?, time_left=?, total_risk_score=?,
                           risk_level=?, session_token=?, session_id=?
                       WHERE id=?""",
                    (
                        safe.get("state", ""),
                        safe.get("time_left", 0),
                        safe.get("total_risk_score", 0),
                        safe.get("risk_level", "TEMIZ"),
                        safe.get("session_token", ""),
                        session_id,
                        row_sc["id"],
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO student_connections
                           (session_id, student_id, login_id, state, exam_id,
                            session_token, time_left, total_risk_score,
                            risk_level, connected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        sid,
                        safe.get("login_id", ""),
                        safe.get("state", ""),
                        exam_id,
                        safe.get("session_token", ""),
                        safe.get("time_left", 0),
                        safe.get("total_risk_score", 0),
                        safe.get("risk_level", "TEMIZ"),
                        time.time(),
                    ),
                )

        conn.commit()


def load_server_state():
    """
    Load server state from SQLite for crash recovery.
    Returns dict with 'active_students' and 'exam_registry', or None if empty.
    """
    conn = _get_conn()
    with _lock:
        try:
            exam_rows = conn.execute("SELECT * FROM exam_sessions").fetchall()
            exam_registry = {}
            for row in exam_rows:
                exam_registry[row["exam_id"]] = {
                    "exam_id": row["exam_id"],
                    "name": row["name"],
                    "duration_minutes": row["duration_minutes"],
                    "state": row["state"],
                    "allowed_apps": json.loads(row["allowed_apps"] or "[]"),
                    "blocked_apps": json.loads(row["blocked_apps"] or "[]"),
                }

            student_rows = conn.execute(
                "SELECT * FROM student_connections WHERE state NOT IN ('completed')"
            ).fetchall()
            active_students = {}
            for row in student_rows:
                active_students[row["student_id"]] = {
                    "ws": None,
                    "state": row["state"] or "",
                    "session_token": row["session_token"] or "",
                    "exam_id": row["exam_id"] or "",
                    "time_left": row["time_left"] or 0,
                    "login_id": row["login_id"] or "",
                    "total_risk_score": row["total_risk_score"] or 0,
                    "risk_level": row["risk_level"] or "TEMIZ",
                }

            if not exam_registry and not active_students:
                return None

            return {"active_students": active_students, "exam_registry": exam_registry}
        except Exception as e:
            print(f"❌ [DB ERROR] Could not load server state: {e}")
            return None


def save_violation_to_db(student_id, violation_type, window_name, new_score):
    """Save a violation record to the violations table."""
    conn = _get_conn()
    with _lock:
        row_sc = conn.execute(
            "SELECT exam_id FROM student_connections"
            " WHERE student_id = ? ORDER BY connected_at DESC LIMIT 1",
            (student_id,),
        ).fetchone()
        exam_id = row_sc["exam_id"] if row_sc else None

        session_id = None
        if exam_id:
            row_s = conn.execute(
                "SELECT id FROM exam_sessions WHERE exam_id = ?", (exam_id,)
            ).fetchone()
            session_id = row_s["id"] if row_s else None

        risk_level = (
            "KRİTİK" if new_score >= 80
            else "YÜKSEK" if new_score >= 40
            else "ORTA"  if new_score > 0
            else "DÜŞÜK"
        )

        conn.execute(
            """INSERT INTO violations
                   (session_id, student_id, violation_type, window_name,
                    risk_score, risk_level, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, student_id, violation_type, window_name,
             new_score, risk_level, time.time()),
        )
        conn.commit()


# ─── ADDITIONAL FUNCTIONS ─────────────────────────────────────────────────────

def create_exam_session(exam_id, payload):
    """Insert or update an exam session. Returns the row id."""
    conn = _get_conn()
    with _lock:
        cursor = conn.execute(
            """INSERT INTO exam_sessions
                   (exam_id, name, duration_minutes, state,
                    allowed_apps, blocked_apps, created_at)
               VALUES (?, ?, ?, 'active', ?, ?, ?)
               ON CONFLICT(exam_id) DO UPDATE SET
                   name=excluded.name,
                   duration_minutes=excluded.duration_minutes,
                   allowed_apps=excluded.allowed_apps,
                   blocked_apps=excluded.blocked_apps""",
            (
                exam_id,
                payload.get("name", ""),
                payload.get("duration_minutes", 40),
                json.dumps(payload.get("allowed_apps", [])),
                json.dumps(payload.get("blocked_apps", [])),
                time.time(),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_student_state(student_id, state):
    """Update the state column of a student connection."""
    conn = _get_conn()
    with _lock:
        conn.execute(
            "UPDATE student_connections SET state = ? WHERE student_id = ?",
            (state, student_id),
        )
        conn.commit()


def record_student_connection(student_id, exam_id, session_token, login_id):
    """Create or refresh a student connection record."""
    conn = _get_conn()
    with _lock:
        row_s = conn.execute(
            "SELECT id FROM exam_sessions WHERE exam_id = ?", (exam_id,)
        ).fetchone()
        session_id = row_s["id"] if row_s else None

        row_sc = conn.execute(
            "SELECT id FROM student_connections WHERE student_id = ? AND exam_id = ?",
            (student_id, exam_id),
        ).fetchone()

        if row_sc:
            conn.execute(
                """UPDATE student_connections SET
                       state='in_progress', session_token=?, login_id=?,
                       connected_at=?, disconnected_at=NULL, session_id=?
                   WHERE id=?""",
                (session_token, login_id, time.time(), session_id, row_sc["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO student_connections
                       (session_id, student_id, login_id, state,
                        exam_id, session_token, connected_at)
                   VALUES (?, ?, ?, 'in_progress', ?, ?, ?)""",
                (session_id, student_id, login_id, exam_id, session_token, time.time()),
            )
        conn.commit()


def record_student_disconnect(student_id):
    """Set disconnected_at for the student's open connection."""
    conn = _get_conn()
    with _lock:
        conn.execute(
            """UPDATE student_connections
               SET disconnected_at = ?
               WHERE student_id = ? AND disconnected_at IS NULL""",
            (time.time(), student_id),
        )
        conn.commit()


def record_monitoring_event(student_id, event_type, event_data, severity):
    """Insert a monitoring event row for a student."""
    conn = _get_conn()
    with _lock:
        row_sc = conn.execute(
            "SELECT exam_id FROM student_connections"
            " WHERE student_id = ? ORDER BY connected_at DESC LIMIT 1",
            (student_id,),
        ).fetchone()
        exam_id = row_sc["exam_id"] if row_sc else None

        session_id = None
        if exam_id:
            row_s = conn.execute(
                "SELECT id FROM exam_sessions WHERE exam_id = ?", (exam_id,)
            ).fetchone()
            session_id = row_s["id"] if row_s else None

        if not isinstance(event_data, str):
            event_data = json.dumps(event_data)

        conn.execute(
            """INSERT INTO monitoring_events
                   (session_id, student_id, event_type, event_data, severity, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, student_id, event_type, event_data, severity, time.time()),
        )
        conn.commit()


def log_audit(action, actor, target, details, result):
    """Append a row to the audit_log table."""
    conn = _get_conn()
    with _lock:
        if not isinstance(details, str):
            details = json.dumps(details)
        conn.execute(
            """INSERT INTO audit_log
                   (action, actor, target, details, result, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (action, actor, target, details, result, time.time()),
        )
        conn.commit()


def get_student_violations(student_id):
    """Return all violations for a student, newest first."""
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT * FROM violations WHERE student_id = ? ORDER BY timestamp DESC",
            (student_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_exam_summary(exam_id):
    """Return a summary dict for the given exam (exam info, students, violations)."""
    conn = _get_conn()
    with _lock:
        exam_row = conn.execute(
            "SELECT * FROM exam_sessions WHERE exam_id = ?", (exam_id,)
        ).fetchone()
        if not exam_row:
            return {}

        students = conn.execute(
            "SELECT * FROM student_connections WHERE exam_id = ?", (exam_id,)
        ).fetchall()

        violations = conn.execute(
            """SELECT v.* FROM violations v
               JOIN exam_sessions e ON v.session_id = e.id
               WHERE e.exam_id = ?""",
            (exam_id,),
        ).fetchall()

        return {
            "exam": dict(exam_row),
            "students": [dict(s) for s in students],
            "violations": [dict(v) for v in violations],
            "student_count": len(students),
            "violation_count": len(violations),
        }


def get_all_violations():
    """Return all violations across all exams, newest first."""
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT * FROM violations ORDER BY timestamp DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def close_db():
    """Close the database connection."""
    global _conn
    with _lock:
        if _conn:
            _conn.close()
            _conn = None


# Auto-create tables on import
init_db()
