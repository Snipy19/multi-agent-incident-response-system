"""
REAL FASTAPI ENDPOINT TESTS
---------------------------
These tests exercise the actual HTTP routes and database layer without
replacing the application with mocked route handlers. A temporary SQLite
database keeps the tests isolated from the developer's local incident data.
"""

from pathlib import Path
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import db.database as database


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a real FastAPI client backed by a fresh temporary database."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "api-test.db"))
    database.init_db()

    # Importing the application after the database path is redirected ensures
    # all endpoint functions use this isolated database connection.
    from main import app

    with TestClient(app) as client:
        yield client


def create_account(client: TestClient, username: str, email: str):
    """Create a test account through the public signup route."""
    response = client.post(
        "/signup",
        json={"username": username, "email": email, "password": "StrongPass123!"},
    )
    assert response.status_code == 200
    return response.json()


def test_health_endpoint_is_public(api_client: TestClient):
    """The service health check should work without an access token."""
    response = api_client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-request-id"]


def test_request_id_is_preserved_when_safe(api_client: TestClient):
    response = api_client.get("/health/live", headers={"X-Request-ID": "manual-check-42"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "manual-check-42"


def test_invalid_request_id_is_replaced(api_client: TestClient):
    response = api_client.get("/health/live", headers={"X-Request-ID": "bad value with spaces"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad value with spaces"


def test_analysis_worker_mode_is_configurable(monkeypatch):
    """The split-service switch has a safe local default and explicit false values."""
    from main import analysis_worker_enabled

    monkeypatch.delenv("ANALYSIS_WORKER_ENABLED", raising=False)
    assert analysis_worker_enabled() is True
    for value in ("0", "false", "no", "off"):
        monkeypatch.setenv("ANALYSIS_WORKER_ENABLED", value)
        assert analysis_worker_enabled() is False


def test_liveness_and_readiness_probes_are_real(api_client: TestClient):
    """Health probes distinguish a live process from a database-ready service."""
    assert api_client.get("/health/live").json() == {"status": "alive"}
    ready = api_client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_cors_allows_authenticated_delete_preflight(api_client: TestClient):
    """A separately hosted frontend can preflight the ownership-scoped delete."""
    response = api_client.options(
        "/incidents/example",
        headers={
            "Origin": "http://127.0.0.1:8000",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8000"
    assert "DELETE" in response.headers["access-control-allow-methods"]


def test_forgot_password_rejects_unknown_username_before_otp_step(api_client):
    """Unknown accounts must not advance to a form for an undeliverable OTP."""
    response = api_client.post("/forgot-password", json={"username": "missing-user"})

    assert response.status_code == 404
    assert "No account exists" in response.json()["detail"]


def test_password_reset_requests_are_rate_limited(api_client):
    """Repeated reset-email requests cannot become an email abuse vector."""
    create_account(api_client, "reset-limit", "reset-limit@example.com")

    responses = [
        api_client.post("/forgot-password", json={"username": "reset-limit"})
        for _ in range(6)
    ]
    assert all(response.status_code == 503 for response in responses[:5])
    assert responses[5].status_code == 429
    assert responses[5].headers["retry-after"] == "3600"


def test_reset_flow_verifies_otp_before_accepting_password(api_client):
    """OTP verification and password policy are enforced by real HTTP routes."""
    create_account(api_client, "resetuser", "resetuser@example.com")
    expires_at = (datetime.now() + timedelta(minutes=10)).isoformat()
    database.save_otp("resetuser", "123456", expires_at)

    invalid_otp = api_client.post(
        "/verify-reset-otp", json={"username": "resetuser", "otp": "000000"}
    )
    assert invalid_otp.status_code == 400

    verified = api_client.post(
        "/verify-reset-otp", json={"username": "resetuser", "otp": "123456"}
    )
    assert verified.status_code == 200

    weak_password = api_client.post(
        "/reset-password",
        json={"username": "resetuser", "otp": "123456", "new_password": "password"},
    )
    assert weak_password.status_code == 400
    assert "uppercase" in weak_password.json()["detail"]

    reset = api_client.post(
        "/reset-password",
        json={
            "username": "resetuser",
            "otp": "123456",
            "new_password": "NewStrong123!",
        },
    )
    assert reset.status_code == 200

    old_login = api_client.post(
        "/login", json={"username": "resetuser", "password": "StrongPass123!"}
    )
    new_login = api_client.post(
        "/login", json={"username": "resetuser", "password": "NewStrong123!"}
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_google_config_uses_backend_environment(api_client, monkeypatch):
    """The browser must receive the same client ID used by token verification."""
    monkeypatch.setenv(
        "GOOGLE_CLIENT_ID",
        "real-client-id.apps.googleusercontent.com",
    )
    response = api_client.get("/auth/google/config")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "client_id": "real-client-id.apps.googleusercontent.com",
    }


def test_google_login_requires_verified_email_and_generates_unique_username(api_client, monkeypatch):
    """Google display names must not collide or bypass email verification."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "real-client-id.apps.googleusercontent.com")
    from google.oauth2 import id_token as google_id_token

    monkeypatch.setattr(
        google_id_token,
        "verify_oauth2_token",
        lambda *args, **kwargs: {
            "sub": "google-sub-123456",
            "email": "verified@example.com",
            "name": "Same Display Name",
            "email_verified": True,
        },
    )
    verified = api_client.post("/auth/google", json={"id_token": "real-token"})
    assert verified.status_code == 200
    assert verified.json()["username"] == "verified"

    monkeypatch.setattr(
        google_id_token,
        "verify_oauth2_token",
        lambda *args, **kwargs: {
            "sub": "google-sub-unverified",
            "email": "unverified@example.com",
            "name": "Unverified",
            "email_verified": False,
        },
    )
    unverified = api_client.post("/auth/google", json={"id_token": "real-token"})
    assert unverified.status_code == 403


def test_signup_and_login_use_real_authentication(api_client: TestClient):
    """Signup creates a user and login returns a usable bearer token."""
    create_account(api_client, "alice", "alice@example.com")

    response = api_client.post(
        "/login",
        json={"username": "alice", "password": "StrongPass123!"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == "alice"
    assert body["access_token"]


def test_browser_auth_uses_httponly_cookie_and_logout_clears_it(api_client: TestClient):
    """The browser session works without exposing the JWT to JavaScript."""
    response = api_client.post(
        "/signup",
        json={"username": "cookieuser", "email": "cookie@example.com", "password": "StrongPass123!"},
    )

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "access_token=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie

    protected = api_client.get("/incidents")
    assert protected.status_code == 200

    signed_out = api_client.post("/logout")
    assert signed_out.status_code == 200
    assert 'access_token=""' in signed_out.headers["set-cookie"]
    assert api_client.get("/incidents").status_code == 401


def test_protected_routes_reject_missing_authentication(api_client: TestClient):
    """Incident data must never be available to anonymous callers."""
    assert api_client.get("/incidents").status_code == 401
    assert api_client.post("/analyze", json={"raw_log": "error"}).status_code == 401


def test_request_validation_rejects_unsafe_input_sizes(api_client: TestClient):
    """Request schemas reject weak credentials and oversized log payloads."""
    weak_signup = api_client.post(
        "/signup",
        json={"username": "short", "email": "short@example.com", "password": "123"},
    )
    account = create_account(api_client, "validator", "validator@example.com")
    oversized_log = api_client.post(
        "/analyze",
        json={"raw_log": "x" * 250_001},
        headers={"Authorization": f"Bearer {account['access_token']}"},
    )

    assert weak_signup.status_code == 422
    assert oversized_log.status_code == 422


def test_load_test_mode_requests_exact_agent_count(api_client: TestClient):
    """The API validates the explicit scalable-investigation test mode."""
    account = create_account(api_client, "loadtester", "loadtester@example.com")
    headers = {"Authorization": f"Bearer {account['access_token']}"}

    missing_count = api_client.post(
        "/analyze",
        json={"raw_log": "CRITICAL service-001 failure", "agent_mode": "load_test"},
        headers=headers,
    )
    too_many = api_client.post(
        "/analyze",
        json={
            "raw_log": "CRITICAL service-001 failure",
            "agent_mode": "load_test",
            "target_agent_count": 101,
        },
        headers=headers,
    )

    assert missing_count.status_code == 422
    assert too_many.status_code == 422


def test_analysis_job_submission_is_durable_and_user_scoped(api_client, monkeypatch):
    """Queued analysis returns immediately and cannot be read by another user."""
    from main import app

    monkeypatch.setattr("main.start_analysis_worker", lambda: None)
    alice = create_account(api_client, "jobalice", "jobalice@example.com")
    bob = create_account(api_client, "jobbob", "jobbob@example.com")
    alice_headers = {"Authorization": f"Bearer {alice['access_token']}"}
    bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}

    queued = api_client.post(
        "/analyze/jobs",
        json={"raw_log": "CRITICAL checkout-api database timeout"},
        headers=alice_headers,
    )
    assert queued.status_code == 202
    job_id = queued.json()["job_id"]
    assert queued.json()["status"] == "queued"

    status = api_client.get(f"/analyze/jobs/{job_id}", headers=alice_headers)
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["events"][0]["type"] == "queued"

    hidden = api_client.get(f"/analyze/jobs/{job_id}", headers=bob_headers)
    assert hidden.status_code == 404


def test_analysis_rate_limit_is_enforced_before_expensive_work(api_client, monkeypatch):
    account = create_account(api_client, "limiteduser", "limited@example.com")
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    monkeypatch.setenv("ANALYSIS_RATE_LIMIT_PER_HOUR", "1")
    monkeypatch.setattr("main.start_analysis_worker", lambda: None)

    first = api_client.post(
        "/analyze/jobs",
        json={"raw_log": "CRITICAL checkout-api database timeout"},
        headers=headers,
    )
    second = api_client.post(
        "/analyze/jobs",
        json={"raw_log": "CRITICAL checkout-api database timeout"},
        headers=headers,
    )

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.headers["retry-after"] == "3600"


def test_incident_data_is_scoped_to_the_authenticated_user(api_client: TestClient):
    """A user's incident list must not expose another user's records."""
    alice = create_account(api_client, "alice", "alice@example.com")
    bob = create_account(api_client, "bob", "bob@example.com")

    # Save a structured incident through the real persistence function. The
    # route tests then verify ownership filtering through the public API.
    database.save_incident(
        "incident-alice",
        database.get_user_by_username("alice")["id"],
        {
            "raw_log": "checkout database timeout",
            "is_anomaly": True,
            "anomaly_reason": "Database connectivity failure",
            "investigation_angles": ["database"],
            "investigation_findings": [{"angle": "database", "finding": "timeout"}],
            "root_cause": "Database connection unavailable",
            "root_cause_confidence": 0.8,
            "suggested_fix": "Check database connectivity",
            "fix_confidence": 0.75,
            "needs_human_review": True,
            "final_report": "Incident report",
        },
    )

    alice_incidents = api_client.get(
        "/incidents", headers={"Authorization": f"Bearer {alice['access_token']}"}
    )
    bob_incidents = api_client.get(
        "/incidents", headers={"Authorization": f"Bearer {bob['access_token']}"}
    )

    assert alice_incidents.status_code == 200
    assert [item["id"] for item in alice_incidents.json()] == ["incident-alice"]
    assert bob_incidents.status_code == 200
    assert bob_incidents.json() == []


def test_user_can_delete_owned_incident(api_client: TestClient):
    """Deletion removes the owned record from both detail and list endpoints."""
    account = create_account(api_client, "delete-user", "delete@example.com")
    user_id = database.get_user_by_username("delete-user")["id"]
    database.save_incident(
        "incident-delete",
        user_id,
        {
            "raw_log": "worker timeout",
            "is_anomaly": True,
            "anomaly_reason": "Timeout",
            "investigation_angles": ["application"],
            "investigation_findings": [{"angle": "application", "finding": "timeout"}],
            "root_cause": "Worker unavailable",
            "root_cause_confidence": 0.7,
            "suggested_fix": "Inspect worker health",
            "fix_confidence": 0.6,
            "needs_human_review": True,
            "final_report": "Incident report",
        },
    )

    deleted = api_client.delete(
        "/incidents/incident-delete",
        headers={"Authorization": f"Bearer {account['access_token']}"},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Incident deleted"}
    assert api_client.get(
        "/incidents/incident-delete",
        headers={"Authorization": f"Bearer {account['access_token']}"},
    ).status_code == 404
    assert api_client.get(
        "/incidents", headers={"Authorization": f"Bearer {account['access_token']}"}
    ).json() == []


def test_user_cannot_delete_another_users_incident(api_client: TestClient):
    """An ownership mismatch behaves as not-found and preserves the record."""
    owner = create_account(api_client, "owner", "owner@example.com")
    other = create_account(api_client, "other", "other@example.com")
    owner_id = database.get_user_by_username("owner")["id"]
    database.save_incident(
        "incident-owned",
        owner_id,
        {
            "raw_log": "service error",
            "is_anomaly": True,
            "anomaly_reason": "Error",
            "investigation_angles": ["application"],
            "investigation_findings": [{"angle": "application", "finding": "error"}],
            "root_cause": "Unknown",
            "root_cause_confidence": 0.2,
            "suggested_fix": "Investigate",
            "fix_confidence": 0.2,
            "needs_human_review": True,
            "final_report": "Incident report",
        },
    )

    denied = api_client.delete(
        "/incidents/incident-owned",
        headers={"Authorization": f"Bearer {other['access_token']}"},
    )
    assert denied.status_code == 404
    assert api_client.get(
        "/incidents/incident-owned",
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    ).status_code == 200


def test_report_download_returns_professional_markdown(api_client: TestClient):
    """An owned incident can be exported through the real report endpoint."""
    account = create_account(api_client, "reporter", "reporter@example.com")
    user_id = database.get_user_by_username("reporter")["id"]
    database.save_incident(
        "incident-report",
        user_id,
        {
            "raw_log": "payment-service returned HTTP 500",
            "is_anomaly": True,
            "anomaly_reason": "Repeated server errors",
            "investigation_angles": ["application"],
            "investigation_findings": [{"angle": "application", "finding": "HTTP 500"}],
            "root_cause": "Unhandled application exception",
            "root_cause_confidence": 0.9,
            "suggested_fix": "Inspect the application error trace",
            "fix_confidence": 0.82,
            "needs_human_review": True,
            "final_report": "Professional incident report",
        },
    )

    response = api_client.get(
        "/incidents/incident-report/report?format=md",
        headers={"Authorization": f"Bearer {account['access_token']}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "Incident Post-Mortem Report" in response.text
    assert "Content-Disposition" in response.headers
