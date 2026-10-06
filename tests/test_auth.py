"""
AUTH UNIT TESTS
------------------
Tests for password hashing and JWT token logic without a database or server.
"""

from auth import hash_password, verify_password, create_access_token, decode_access_token


def test_password_hash_is_not_plaintext():
    """A password hash must not expose the original password."""
    password = "mySecret123"
    hashed = hash_password(password)
    assert hashed != password
    assert len(hashed) > 20  # bcrypt hashes have substantial length


def test_verify_password_correct():
    """The correct password must verify successfully."""
    password = "mySecret123"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


def test_verify_password_incorrect():
    """An incorrect password must not verify."""
    hashed = hash_password("mySecret123")
    assert verify_password("wrongPassword", hashed) is False


def test_create_and_decode_token():
    """Decoding a newly created token must return the correct user data."""
    token = create_access_token("user-123", "testuser")
    payload = decode_access_token(token)

    assert payload is not None
    assert payload["user_id"] == "user-123"
    assert payload["username"] == "testuser"


def test_decode_invalid_token_returns_none():
    """An invalid token must return None rather than raising an exception."""
    payload = decode_access_token("this.is.not.a.valid.token")
    assert payload is None
