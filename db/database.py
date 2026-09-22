"""
DATABASE LAYER
------------------
Kaam: Har incident (log, findings, root cause, fix, report) ko
SQLite database mein store karna, taaki:
1. History query ho sake (sab purane incidents dekh sakein)
2. Data local .txt files pe depend na kare
3. Baad mein AWS deploy karte waqt, isi structure ko DynamoDB mein
   easily migrate kar sakein (interface same rahega)
"""

import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

DB_PATH = "db/incidents.db"


@contextmanager
def get_connection():
    """
    Ek helper jo database connection open/close automatically
    handle karta hai - taaki har jagah manually connection
    close karna na bhoole.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows ko dictionary jaisa access karne dega
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """
    Table banata hai agar exist nahi karta. Ye app start hote hi
    ek baar call hota hai (main.py mein).
    """
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
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
    print("[DATABASE] Table ready hai (incidents)")


def save_incident(incident_id: str, result: dict):
    """
    Ek naya incident record save karta hai.
    incident_id: unique ID (hum UUID use karenge)
    result: graph ka poora output dictionary
    """
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO incidents (
                id, created_at, raw_log, is_anomaly, anomaly_reason,
                investigation_angles, investigation_findings,
                root_cause, root_cause_confidence,
                suggested_fix, fix_confidence,
                needs_human_review, final_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident_id,
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
    print(f"[DATABASE] Incident {incident_id} save ho gaya")


def get_all_incidents(limit: int = 50):
    """
    Sab incidents wapas deta hai, sabse naya pehle. Frontend ki
    'Past Incidents' list ke liye use hoga.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, created_at, raw_log, root_cause, root_cause_confidence, needs_human_review "
            "FROM incidents ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_incident_by_id(incident_id: str):
    """
    Ek specific incident ka poora detail deta hai, uski ID se.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        # JSON string wapas Python list/dict mein convert karte hain
        data["investigation_angles"] = json.loads(data["investigation_angles"])
        data["investigation_findings"] = json.loads(data["investigation_findings"])
        return data