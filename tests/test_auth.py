"""
AUTH UNIT TESTS
------------------
Kaam: password hashing aur JWT token logic ko test karna, bina
database ya server ke zarurat ke.
"""

from auth import hash_password, verify_password, create_access_token, decode_access_token


def test_password_hash_is_not_plaintext():
    """Hash kiya hua password original password jaisa nahi dikhna chahiye"""
    password = "mySecret123"
    hashed = hash_password(password)
    assert hashed != password
    assert len(hashed) > 20  # bcrypt hash hamesha lamba hota hai


def test_verify_password_correct():
    """Sahi password verify hona chahiye"""
    password = "mySecret123"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


def test_verify_password_incorrect():
    """Galat password verify NAHI hona chahiye"""
    hashed = hash_password("mySecret123")
    assert verify_password("wrongPassword", hashed) is False


def test_create_and_decode_token():
    """Token banane ke baad decode karne se sahi user info milni chahiye"""
    token = create_access_token("user-123", "testuser")
    payload = decode_access_token(token)

    assert payload is not None
    assert payload["user_id"] == "user-123"
    assert payload["username"] == "testuser"


def test_decode_invalid_token_returns_none():
    """Galat/corrupted token decode karne pe None milna chahiye, crash nahi"""
    payload = decode_access_token("this.is.not.a.valid.token")
    assert payload is None