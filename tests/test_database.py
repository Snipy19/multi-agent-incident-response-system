from datetime import datetime, timedelta, timezone

import pytest

import db.database as database


@pytest.fixture()
def isolated_database(tmp_path, monkeypatch):
    """Use a real SQLite file, isolated from the application's development DB."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "incidents-test.db"))
    database.init_db()
    return database


def incident_result():
    # This fixture represents the structured output saved after a real run.
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
        "root_cause_certainty": "Strong hypothesis",
        "root_cause_confidence_reason": "The timeout is directly observed, but reachability is unverified.",
        "root_cause_evidence": ["The request timed out."],
        "root_cause_missing_evidence": ["A reachability check."],
        "root_cause_alternatives": ["Application saturation."],
        "suggested_fix": "Check upstream service health.",
        "fix_confidence": 0.75,
        "fix_certainty": "Strong hypothesis",
        "fix_confidence_reason": "The fix validates the dependency before changing production.",
        "fix_evidence": ["The dependency timed out."],
        "fix_missing_evidence": ["Current dependency metrics."],
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
    stored_otp = isolated_database.get_otp("alice")["otp"]
    assert stored_otp != "123456"
    assert isolated_database.verify_otp(stored_otp, "123456")
    assert not isolated_database.verify_otp(stored_otp, "000000")

    isolated_database.delete_otp("alice")
    assert isolated_database.get_otp("alice") is None


def test_incident_round_trip_is_private_to_user(isolated_database):
    # Incident ownership must be enforced at the query boundary.
    isolated_database.save_incident("incident-1", "user-1", incident_result())

    stored = isolated_database.get_incident_by_id("incident-1", "user-1")
    assert stored["is_anomaly"] == 1
    assert stored["investigation_angles"] == ["API", "Network"]
    assert stored["investigation_findings"][0]["confidence"] == 0.9
    assert stored["root_cause"] == "The upstream service was unavailable."
    assert stored["root_cause_certainty"] == "Strong hypothesis"
    assert stored["root_cause_evidence"] == ["The request timed out."]
    assert stored["fix_missing_evidence"] == ["Current dependency metrics."]
    assert "directly observed" in stored["root_cause_confidence_reason"]
    assert "validates the dependency" in stored["fix_confidence_reason"]

    assert isolated_database.get_incident_by_id("incident-1", "different-user") is None
    assert isolated_database.get_all_incidents("different-user") == []


def test_duplicate_username_is_rejected_by_database(isolated_database):
    isolated_database.create_user("user-1", "alice", "alice@example.com", "hash")

    with pytest.raises(Exception):
        isolated_database.create_user("user-2", "alice", "other@example.com", "hash")


def test_analysis_job_claim_and_completion_round_trip(isolated_database):
    isolated_database.create_analysis_job(
        "job-1",
        "user-1",
        {"raw_log": "ERROR timeout", "agent_mode": "adaptive"},
    )

    claimed = isolated_database.claim_next_analysis_job()
    assert claimed["id"] == "job-1"
    assert claimed["status"] == "running"
    assert claimed["heartbeat_at"] is not None
    assert claimed["request_state"]["raw_log"] == "ERROR timeout"
    assert claimed["events"][0]["type"] == "queued"

    isolated_database.complete_analysis_job("job-1", {"incident_id": "incident-1"})
    stored = isolated_database.get_analysis_job("job-1", "user-1")
    assert stored["status"] == "completed"
    assert stored["result"] == {"incident_id": "incident-1"}
    assert stored["heartbeat_at"] is None


def test_analysis_metrics_summary_is_durable_and_user_scoped(isolated_database):
    isolated_database.create_analysis_job(
        "job-metrics-complete",
        "user-1",
        {"raw_log": "ERROR timeout", "agent_mode": "adaptive"},
    )
    isolated_database.complete_analysis_job(
        "job-metrics-complete",
        {"incident_id": "incident-1"},
        metrics={
            "cost_usd": 0.12,
            "queue_wait_ms": 5.0,
            "execution_duration_ms": 250.0,
        },
    )
    isolated_database.create_analysis_job(
        "job-metrics-failed",
        "user-1",
        {"raw_log": "ERROR timeout", "agent_mode": "adaptive"},
    )
    isolated_database.fail_analysis_job(
        "job-metrics-failed",
        "provider_error",
        metrics={"cost_usd": None},
    )
    isolated_database.create_analysis_job(
        "job-other-user",
        "user-2",
        {"raw_log": "ERROR timeout", "agent_mode": "adaptive"},
    )

    stored = isolated_database.get_analysis_job("job-metrics-complete", "user-1")
    summary = isolated_database.get_analysis_metrics_summary("user-1")

    assert stored["metrics"]["cost_usd"] == 0.12
    assert stored["metrics"]["queue_wait_ms"] == 5.0
    assert summary["total_analyses"] == 2
    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["failure_rate"] == 0.5
    assert summary["known_cost_usd"] == 0.12
    assert summary["cost_coverage"] == 0.5


def test_failed_analysis_job_stores_only_a_safe_error_code(isolated_database):
    isolated_database.create_analysis_job(
        "job-failure",
        "user-1",
        {"raw_log": "ERROR timeout", "agent_mode": "adaptive"},
    )

    isolated_database.fail_analysis_job(
        "job-failure",
        "api_key=secret-value provider response with incident details",
    )

    stored = isolated_database.get_analysis_job("job-failure", "user-1")
    assert stored["status"] == "failed"
    assert stored["error"] == "analysis_failed"
    assert "secret-value" not in stored["error"]


def test_stale_running_analysis_job_is_requeued(isolated_database):
    isolated_database.create_analysis_job(
        "job-stale",
        "user-1",
        {"raw_log": "ERROR timeout", "agent_mode": "adaptive"},
    )
    claimed = isolated_database.claim_next_analysis_job()
    assert claimed["status"] == "running"

    with isolated_database.get_connection() as conn:
        conn.execute(
            "UPDATE analysis_jobs SET started_at = ?, heartbeat_at = ? WHERE id = ?",
            (
                (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat(),
                (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat(),
                "job-stale",
            ),
        )

    isolated_database.requeue_stale_analysis_jobs()
    assert isolated_database.get_analysis_job("job-stale", "user-1")["status"] == "queued"


def test_recent_job_heartbeat_prevents_stale_requeue(isolated_database):
    isolated_database.create_analysis_job(
        "job-active",
        "user-1",
        {"raw_log": "ERROR timeout", "agent_mode": "adaptive"},
    )
    isolated_database.claim_next_analysis_job()

    with isolated_database.get_connection() as conn:
        old = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
        recent = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE analysis_jobs SET started_at = ?, heartbeat_at = ? WHERE id = ?",
            (old, recent, "job-active"),
        )

    isolated_database.requeue_stale_analysis_jobs()
    assert isolated_database.get_analysis_job("job-active", "user-1")["status"] == "running"


def test_persistent_rate_limit_resets_after_window(isolated_database):
    assert isolated_database.consume_rate_limit("analysis:user-1", 2, 60)
    assert isolated_database.consume_rate_limit("analysis:user-1", 2, 60)
    assert not isolated_database.consume_rate_limit("analysis:user-1", 2, 60)

    with isolated_database.get_connection() as conn:
        conn.execute(
            "UPDATE rate_limits SET window_started_at = ? WHERE rate_key = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=61)).isoformat(), "analysis:user-1"),
        )

    assert isolated_database.consume_rate_limit("analysis:user-1", 2, 60)
