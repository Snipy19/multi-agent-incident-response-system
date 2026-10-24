"""Real PostgreSQL integration coverage for the production persistence path."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import db.database as database


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is not configured",
)


def test_postgres_schema_and_security_round_trip(monkeypatch):
    """Exercise the real PostgreSQL adapter, not a mocked connection."""
    monkeypatch.setattr(database, "DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    suffix = uuid.uuid4().hex
    user_id = f"postgres-test-{suffix}"
    username = f"postgres_{suffix}"
    rate_key = f"postgres-test:{suffix}"

    try:
        database.init_db()
        database.create_user(user_id, username, f"{username}@example.com", "hash")
        assert database.get_user_by_username(username)["id"] == user_id

        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        database.save_otp(username, "123456", expires_at)
        stored = database.get_otp(username)["otp"]
        assert stored != "123456"
        assert database.verify_otp(stored, "123456")
        assert not database.verify_otp(stored, "000000")

        assert database.consume_rate_limit(rate_key, 1, 60)
        assert not database.consume_rate_limit(rate_key, 1, 60)
    finally:
        with database.get_connection() as conn:
            conn.execute("DELETE FROM password_reset_otps WHERE username = ?", (username,))
            conn.execute("DELETE FROM rate_limits WHERE rate_key = ?", (rate_key,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
