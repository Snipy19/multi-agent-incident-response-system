"""
AUTH HELPER
--------------
Password hashing with bcrypt and JWT token creation/verification.
"""

import os
import warnings
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt, JWTError

# Production tokens must use a secret supplied by the deployment environment.
# A development-only fallback keeps local setup simple but can never be used in
# a production deployment without an explicit startup failure.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    if ENVIRONMENT == "production":
        raise RuntimeError("JWT_SECRET_KEY must be configured in production")
    SECRET_KEY = "local-development-secret-change-me"
    warnings.warn(
        "JWT_SECRET_KEY is not configured; using a development-only secret.",
        RuntimeWarning,
        stacklevel=2,
    )
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str, username: str) -> str:
    # Use an explicit UTC timezone so token expiry remains correct across
    # machines and avoids the deprecated naive-UTC datetime API.
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": user_id, "username": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str):
    """Verify a token and return user information, or None if invalid or expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"user_id": payload["sub"], "username": payload["username"]}
    except JWTError:
        return None
