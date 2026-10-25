"""
DATABASE LAYER
------------------
SQLite persistence for local development and PostgreSQL persistence for
production deployments. Both backends expose the same application contract.
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
import json
import re
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = "db/incidents.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def _uses_postgres() -> bool:
    return DATABASE_URL.startswith(("postgres://", "postgresql://"))


class _ConnectionAdapter:
    """Keep the existing qmark SQL contract across SQLite and psycopg."""

    def __init__(self, connection, postgres: bool):
        self._connection = connection
        self.postgres = postgres

    def execute(self, query: str, parameters=()):
        if self.postgres:
            query = query.replace("BEGIN IMMEDIATE", "BEGIN").replace("?", "%s")
        return self._connection.execute(query, parameters)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _open_connection() -> _ConnectionAdapter:
    if _uses_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL is configured for PostgreSQL, but psycopg is not installed"
            ) from exc
        return _ConnectionAdapter(
            psycopg.connect(DATABASE_URL, row_factory=dict_row),
            postgres=True,
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return _ConnectionAdapter(conn, postgres=False)


@contextmanager
def get_connection():
    # A fresh connection per operation keeps local SQLite usage isolated and
    # lets PostgreSQL use its normal connection/transaction semantics.
    conn = _open_connection()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    # CREATE TABLE IF NOT EXISTS makes startup safe for a new local checkout.
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
                root_cause_certainty TEXT,
                root_cause_confidence_reason TEXT,
                root_cause_evidence TEXT,
                root_cause_missing_evidence TEXT,
                root_cause_alternatives TEXT,
                suggested_fix TEXT,
                fix_confidence REAL,
                fix_certainty TEXT,
                fix_confidence_reason TEXT,
                fix_evidence TEXT,
                fix_missing_evidence TEXT,
                needs_human_review INTEGER,
                final_report TEXT
            )
        """)
        # Existing local databases predate the confidence-basis fields. Keep
        # them usable and make downloaded reports match the live result.
        if _uses_postgres():
            columns = {
                row["column_name"]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = ?",
                    ("incidents",),
                ).fetchall()
            }
        else:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(incidents)").fetchall()
            }
        columns_to_add = {
            "root_cause_certainty": "TEXT",
            "root_cause_confidence_reason": "TEXT",
            "root_cause_evidence": "TEXT",
            "root_cause_missing_evidence": "TEXT",
            "root_cause_alternatives": "TEXT",
            "fix_certainty": "TEXT",
            "fix_confidence_reason": "TEXT",
            "fix_evidence": "TEXT",
            "fix_missing_evidence": "TEXT",
        }
        for column, column_type in columns_to_add.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE incidents ADD COLUMN {column} {column_type}")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_otps (
                username TEXT PRIMARY KEY,
                otp TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                request_state TEXT NOT NULL,
                status TEXT NOT NULL,
                events TEXT NOT NULL DEFAULT '[]',
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                heartbeat_at TEXT,
                completed_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                rate_key TEXT PRIMARY KEY,
                window_started_at TEXT NOT NULL,
                request_count INTEGER NOT NULL
            )
        """)
        if _uses_postgres():
            job_columns = {
                row["column_name"]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = ?",
                    ("analysis_jobs",),
                ).fetchall()
            }
        else:
            job_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(analysis_jobs)").fetchall()
            }
        if "events" not in job_columns:
            conn.execute("ALTER TABLE analysis_jobs ADD COLUMN events TEXT NOT NULL DEFAULT '[]'")
        if "heartbeat_at" not in job_columns:
            conn.execute("ALTER TABLE analysis_jobs ADD COLUMN heartbeat_at TEXT")
    backend = "postgresql" if _uses_postgres() else "sqlite"
    print(f"[DATABASE] Tables are ready ({backend}): users, incidents, password_reset_otps, analysis_jobs")


# ---------- USER FUNCTIONS (password-based) ----------

def create_user(user_id: str, username: str, email: str, password_hash: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (id, username, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, email, password_hash, datetime.now(timezone.utc).isoformat())
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

_OTP_HASH_PREFIX = "hmac-sha256$"


def _otp_digest(otp: str) -> str:
    """Hash an OTP so a database read does not reveal the active code."""
    secret = os.getenv("OTP_HASH_SECRET") or os.getenv("JWT_SECRET_KEY") or "local-otp-secret"
    digest = hmac.new(secret.encode("utf-8"), otp.encode("utf-8"), hashlib.sha256)
    return _OTP_HASH_PREFIX + digest.hexdigest()

def save_otp(username: str, otp: str, expires_at: str):
    with get_connection() as conn:
        values = (username, _otp_digest(otp), expires_at, datetime.now(timezone.utc).isoformat())
        if _uses_postgres():
            conn.execute(
                "INSERT INTO password_reset_otps (username, otp, expires_at, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (username) DO UPDATE SET "
                "otp = EXCLUDED.otp, expires_at = EXCLUDED.expires_at, created_at = EXCLUDED.created_at",
                values,
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO password_reset_otps (username, otp, expires_at, created_at) VALUES (?, ?, ?, ?)",
                values,
            )


def verify_otp(stored_otp: str, candidate_otp: str) -> bool:
    """Verify new digests and temporary legacy plaintext rows during migration."""
    if stored_otp.startswith(_OTP_HASH_PREFIX):
        return secrets.compare_digest(stored_otp, _otp_digest(candidate_otp))
    # Rows created by older versions are still usable once, without forcing
    # every local database to be manually migrated before password recovery.
    return secrets.compare_digest(stored_otp, candidate_otp)


def consume_otp(username: str, candidate_otp: str) -> bool:
    """Atomically consume a valid, unexpired OTP exactly once."""
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        # Serialize the read/delete pair so concurrent password-reset requests
        # cannot both use the same one-time code.
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT otp, expires_at FROM password_reset_otps WHERE username = ?"
            + (" FOR UPDATE" if _uses_postgres() else ""),
            (username,),
        ).fetchone()
        if row is None:
            return False

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now > expires_at or not verify_otp(row["otp"], candidate_otp):
            return False

        deleted = conn.execute(
            "DELETE FROM password_reset_otps WHERE username = ?",
            (username,),
        ).rowcount
        return deleted == 1


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
    # Store the complete structured workflow result so reports can be rebuilt
    # later without calling the LLM again.
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO incidents (
                id, user_id, created_at, raw_log, is_anomaly, anomaly_reason,
                investigation_angles, investigation_findings,
                root_cause, root_cause_confidence, root_cause_certainty,
                root_cause_confidence_reason, root_cause_evidence,
                root_cause_missing_evidence, root_cause_alternatives,
                suggested_fix, fix_confidence, fix_certainty,
                fix_confidence_reason, fix_evidence, fix_missing_evidence,
                needs_human_review, final_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident_id,
            user_id,
            datetime.now(timezone.utc).isoformat(),
            result["raw_log"],
            int(result["is_anomaly"]) if result["is_anomaly"] is not None else None,
            result["anomaly_reason"],
            json.dumps(result["investigation_angles"]),
            json.dumps(result["investigation_findings"]),
            result["root_cause"],
            result["root_cause_confidence"],
            result.get("root_cause_certainty"),
            result.get("root_cause_confidence_reason"),
            json.dumps(result.get("root_cause_evidence") or []),
            json.dumps(result.get("root_cause_missing_evidence") or []),
            json.dumps(result.get("root_cause_alternatives") or []),
            result["suggested_fix"],
            result["fix_confidence"],
            result.get("fix_certainty"),
            result.get("fix_confidence_reason"),
            json.dumps(result.get("fix_evidence") or []),
            json.dumps(result.get("fix_missing_evidence") or []),
            int(result["needs_human_review"]) if result["needs_human_review"] is not None else None,
            result["final_report"]
        ))
    print(f"[DATABASE] Saved incident {incident_id} for user {user_id}")


def get_all_incidents(user_id: str, limit: int = 50):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, created_at, raw_log, root_cause, root_cause_confidence, "
            "root_cause_certainty, needs_human_review "
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
        data["investigation_angles"] = json.loads(data["investigation_angles"] or "[]")
        data["investigation_findings"] = json.loads(data["investigation_findings"] or "[]")
        for field in (
            "root_cause_evidence", "root_cause_missing_evidence",
            "root_cause_alternatives", "fix_evidence", "fix_missing_evidence",
        ):
            data[field] = json.loads(data[field] or "[]")
        return data


def delete_incident(incident_id: str, user_id: str) -> bool:
    """Delete one incident only when it belongs to the authenticated user."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM incidents WHERE id = ? AND user_id = ?",
            (incident_id, user_id),
        )
        return cursor.rowcount == 1


# ---------- ANALYSIS JOB QUEUE ----------

def create_analysis_job(job_id: str, user_id: str, request_state: dict):
    """Persist a queued analysis before a worker is allowed to execute it."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO analysis_jobs
               (id, user_id, request_state, status, events, created_at)
               VALUES (?, ?, ?, 'queued', ?, ?)""",
            (
                job_id,
                user_id,
                json.dumps(request_state),
                json.dumps([{"type": "queued", "message": "Analysis queued."}]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_analysis_job(job_id: str, user_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM analysis_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["request_state"] = json.loads(data["request_state"])
    data["events"] = json.loads(data.get("events") or "[]")
    data["result"] = json.loads(data["result"]) if data["result"] else None
    return data


def claim_next_analysis_job():
    """Claim one queued job; one local worker owns a job at a time."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM analysis_jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        changed = conn.execute(
            """UPDATE analysis_jobs SET status = 'running', started_at = ?, heartbeat_at = ?
               WHERE id = ? AND status = 'queued'""",
            (now, now, row["id"]),
        ).rowcount
        if changed != 1:
            return None
        claimed = conn.execute(
            "SELECT * FROM analysis_jobs WHERE id = ?", (row["id"],)
        ).fetchone()
    data = dict(claimed)
    data["request_state"] = json.loads(data["request_state"])
    data["events"] = json.loads(data.get("events") or "[]")
    return data


def requeue_stale_analysis_jobs(max_age_minutes: int = 30):
    """Return jobs abandoned by a crashed worker to the durable queue."""
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_minutes * 60)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, started_at, heartbeat_at FROM analysis_jobs WHERE status = 'running'"
        ).fetchall()
        for row in rows:
            last_seen = row["heartbeat_at"] or row["started_at"]
            if not last_seen:
                continue
            parsed = datetime.fromisoformat(last_seen)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed.timestamp() < cutoff:
                conn.execute(
                    """UPDATE analysis_jobs
                       SET status = 'queued', started_at = NULL, heartbeat_at = NULL,
                           error = 'Worker restarted before the analysis completed.'
                       WHERE id = ? AND status = 'running'""",
                    (row["id"],),
                )


def heartbeat_analysis_job(job_id: str):
    """Renew a running job lease so active work is not requeued as stale."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE analysis_jobs SET heartbeat_at = ?
               WHERE id = ? AND status = 'running'""",
            (datetime.now(timezone.utc).isoformat(), job_id),
        )


def append_analysis_job_event(job_id: str, event: dict):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT events FROM analysis_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return
        events = json.loads(row["events"] or "[]")
        events.append(event)
        conn.execute(
            "UPDATE analysis_jobs SET events = ? WHERE id = ?",
            (json.dumps(events), job_id),
        )


def complete_analysis_job(job_id: str, result: dict):
    with get_connection() as conn:
        conn.execute(
            """UPDATE analysis_jobs
               SET status = 'completed', result = ?, completed_at = ?, heartbeat_at = NULL
               WHERE id = ?""",
            (json.dumps(result), datetime.now(timezone.utc).isoformat(), job_id),
        )


def fail_analysis_job(job_id: str, error: str):
    """Mark a job failed without persisting provider or request details.

    Callers may have an exception object or an untrusted provider message.
    Store only a short machine-readable error code; raw exception details must
    stay out of the application database.
    """
    candidate = str(error or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", candidate):
        candidate = "analysis_failed"
    with get_connection() as conn:
        conn.execute(
            """UPDATE analysis_jobs SET status = 'failed', error = ?, completed_at = ?, heartbeat_at = NULL
               WHERE id = ?""",
            (candidate, datetime.now(timezone.utc).isoformat(), job_id),
        )


def consume_rate_limit(rate_key: str, limit: int, window_seconds: int) -> bool:
    """Atomically consume one request from a persistent fixed-window limit."""
    if limit < 1 or window_seconds < 1:
        raise ValueError("limit and window_seconds must be positive")

    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        # Serialize the read/update pair so concurrent API requests cannot
        # both pass the last available slot in the same SQLite process.
        if _uses_postgres():
            conn.execute("BEGIN")
            inserted = conn.execute(
                "INSERT INTO rate_limits (rate_key, window_started_at, request_count) "
                "VALUES (?, ?, 1) ON CONFLICT (rate_key) DO NOTHING RETURNING rate_key",
                (rate_key, now.isoformat()),
            ).fetchone()
            if inserted is not None:
                return True
        else:
            conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT window_started_at, request_count FROM rate_limits WHERE rate_key = ?"
            + (" FOR UPDATE" if _uses_postgres() else ""),
            (rate_key,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO rate_limits (rate_key, window_started_at, request_count) VALUES (?, ?, 1)",
                (rate_key, now.isoformat()),
            )
            return True

        window_started = datetime.fromisoformat(row["window_started_at"])
        if window_started.tzinfo is None:
            window_started = window_started.replace(tzinfo=timezone.utc)
        if (now - window_started).total_seconds() >= window_seconds:
            conn.execute(
                "UPDATE rate_limits SET window_started_at = ?, request_count = 1 WHERE rate_key = ?",
                (now.isoformat(), rate_key),
            )
            return True

        if row["request_count"] >= limit:
            return False

        conn.execute(
            "UPDATE rate_limits SET request_count = request_count + 1 WHERE rate_key = ?",
            (rate_key,),
        )
        return True
