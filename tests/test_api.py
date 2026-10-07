"""
REAL FASTAPI ENDPOINT TESTS
---------------------------
These tests exercise the actual HTTP routes and database layer without
replacing the application with mocked route handlers. A temporary SQLite
database keeps the tests isolated from the developer's local incident data.
"""

from pathlib import Path

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
