"""
DATABASE LAYER
------------------
Kaam: Users (password-based aur Google-based), incidents, aur
password-reset OTPs ko SQLite mein store karna.
"""

import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

DB_PATH = "db/incidents.db"


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT,
                google_id TEXT UNIQUE,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                raw_log TEXT NOT NULL,
                is_anomaly INTEGER,
                anomaly_reason TEXT,
                investigation_angles TEXT,
                investigation_findings TEXT,
                root_cause TEXT,
                root_cause_confidence REAL,
                suggested_fix TEXT,
                fix_confidence REAL,
                needs_human_review INTEGER,
                final_report TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_otps (
                username TEXT PRIMARY KEY,
                otp TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
    print("[DATABASE] Tables ready hain (users, incidents, password_reset_otps)")


# ---------- USER FUNCTIONS (password-based) ----------

def create_user(user_id: str, username: str, email: str, password_hash: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (id, username, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, email, password_hash, datetime.now().isoformat())
        )


def get_user_by_username(username: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        return dict(row) if row else None


def update_user_password(username: str, new_password_hash: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (new_password_hash, username)
        )


# ---------- USER FUNCTIONS (Google-based) ----------

def get_user_by_google_id(google_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE google_id = ?", (google_id,)
        ).fetchone()
        return dict(row) if row else None


def create_google_user(user_id: str, username: str, email: str, google_id: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (id, username, email, password_hash, google_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, email, None, google_id, datetime.now().isoformat())
        )


# ---------- PASSWORD RESET OTP FUNCTIONS ----------

def save_otp(username: str, otp: str, expires_at: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO password_reset_otps (username, otp, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (username, otp, expires_at, datetime.now().isoformat())
        )


def get_otp(username: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM password_reset_otps WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def delete_otp(username: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM password_reset_otps WHERE username = ?", (username,))


# ---------- INCIDENT FUNCTIONS ----------

def save_incident(incident_id: str, user_id: str, result: dict):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO incidents (
                id, user_id, created_at, raw_log, is_anomaly, anomaly_reason,
                investigation_angles, investigation_findings,
                root_cause, root_cause_confidence,
                suggested_fix, fix_confidence,
                needs_human_review, final_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident_id,
            user_id,
            datetime.now().isoformat(),
            result["raw_log"],
            int(result["is_anomaly"]) if result["is_anomaly"] is not None else None,
            result["anomaly_reason"],
            json.dumps(result["investigation_angles"]),
            json.dumps(result["investigation_findings"]),
            result["root_cause"],
            result["root_cause_confidence"],
            result["suggested_fix"],
            result["fix_confidence"],
            int(result["needs_human_review"]) if result["needs_human_review"] is not None else None,
            result["final_report"]
        ))
    print(f"[DATABASE] Incident {incident_id} save ho gaya user {user_id} ke liye")


def get_all_incidents(user_id: str, limit: int = 50):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, created_at, raw_log, root_cause, root_cause_confidence, needs_human_review "
            "FROM incidents WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(row) for row in rows]


def get_incident_by_id(incident_id: str, user_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM incidents WHERE id = ? AND user_id = ?", (incident_id, user_id)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["investigation_angles"] = json.loads(data["investigation_angles"])
        data["investigation_findings"] = json.loads(data["investigation_findings"])
        return data