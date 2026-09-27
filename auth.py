"""
AUTH HELPER
--------------
Password hashing (bcrypt) aur JWT token banane/verify karne ka logic.
"""

import os
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import jwt, JWTError

# Secret key - production mein isko .env se lena chahiye, abhi ke liye
# hardcoded hai development ke liye. AWS deploy karte waqt .env mein daalenge.
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production-abc123xyz")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str, username: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": user_id, "username": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str):
    """Token ko verify karta hai, return karta hai user_id ya None agar invalid/expired hai"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"user_id": payload["sub"], "username": payload["username"]}
    except JWTError:
        return None