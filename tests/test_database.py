from datetime import datetime, timedelta

import pytest

import db.database as database


@pytest.fixture()
def isolated_database(tmp_path, monkeypatch):
    """Use a real SQLite file, isolated from the application's development DB."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "incidents-test.db"))
    database.init_db()
    return database


def incident_result():
    return {
        "raw_log": "ERROR: API request timed out",
        "is_anomaly": True,
        "anomaly_reason": "The request exceeded its timeout.",
        "investigation_angles": ["API", "Network"],
        "investigation_findings": [
            {"angle": "API", "finding": "The API did not respond in time.", "confidence": 0.9}
        ],
        "root_cause": "The upstream service was unavailable.",
        "root_cause_confidence": 0.8,
        "suggested_fix": "Check upstream service health.",
        "fix_confidence": 0.75,
        "needs_human_review": False,
        "final_report": "Incident report",
    }


def test_user_and_password_reset_data_round_trip(isolated_database):
    isolated_database.create_user("user-1", "alice", "alice@example.com", "hash")

    assert isolated_database.get_user_by_username("alice")["email"] == "alice@example.com"
    assert isolated_database.get_user_by_email("alice@example.com")["username"] == "alice"

    isolated_database.update_user_password("alice", "new-hash")
    assert isolated_database.get_user_by_username("alice")["password_hash"] == "new-hash"

    expires_at = (datetime.now() + timedelta(minutes=10)).isoformat()
    isolated_database.save_otp("alice", "123456", expires_at)
    assert isolated_database.get_otp("alice")["otp"] == "123456"

    isolated_database.delete_otp("alice")
    assert isolated_database.get_otp("alice") is None


def test_incident_round_trip_is_private_to_user(isolated_database):
    isolated_database.save_incident("incident-1", "user-1", incident_result())

    stored = isolated_database.get_incident_by_id("incident-1", "user-1")
    assert stored["is_anomaly"] == 1
    assert stored["investigation_angles"] == ["API", "Network"]
    assert stored["investigation_findings"][0]["confidence"] == 0.9
    assert stored["root_cause"] == "The upstream service was unavailable."

    assert isolated_database.get_incident_by_id("incident-1", "different-user") is None
    assert isolated_database.get_all_incidents("different-user") == []


def test_duplicate_username_is_rejected_by_database(isolated_database):
    isolated_database.create_user("user-1", "alice", "alice@example.com", "hash")

    with pytest.raises(Exception):
        isolated_database.create_user("user-2", "alice", "other@example.com", "hash")
