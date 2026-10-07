"""
FASTAPI BACKEND (username/password + Google + Forgot Password/OTP + report downloads)
-----------------------------------------------------------------------------------------
The API owns authentication, incident persistence, report downloads, and the
entry point for the LangGraph analysis workflow. The frontend is served at /ui
so local OAuth uses the same origin as the API.
"""

import os
import uuid
import random
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from db.database import (
    init_db, save_incident, get_all_incidents, get_incident_by_id,
    create_user, get_user_by_username, get_user_by_email, update_user_password,
    get_user_by_google_id, create_google_user,
    save_otp, get_otp, delete_otp
)
from auth import hash_password, verify_password, create_access_token, decode_access_token
from utils.email_helper import send_otp_email
from utils.report_export import build_markdown, build_text, build_pdf


def get_graph_app():
    """Load the expensive LangGraph/RAG pipeline only for a real analysis."""
    # Lazy loading keeps authentication, health checks, report downloads, and
    # CI tests fast without changing the real analysis path.
    from graph import app as graph_app
    return graph_app

app = FastAPI(title="Autonomous Incident Response API")

init_db()

app.add_middleware(
    CORSMiddleware,
    # Explicit origins prevent arbitrary websites from calling the API from a
    # browser. Set CORS_ORIGINS as a comma-separated list in deployment.
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://127.0.0.1:8000,http://localhost:8000",
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Serve the frontend from the same origin as the API in local and container
# deployments. This keeps Google OAuth on the configured localhost origin and
# avoids frontend/API port mismatches during development.
app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)


def get_current_user(token: str = Depends(oauth2_scheme)):
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


# ---------- REQUEST SCHEMAS ----------
# Pydantic validates request bodies before endpoint logic runs.

class LogRequest(BaseModel):
    # Limit payload size so a single request cannot consume excessive memory
    # or trigger an unexpectedly expensive LLM investigation.
    raw_log: str = Field(..., min_length=1, max_length=250_000)


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(..., min_length=1, max_length=8192)


class ForgotPasswordRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)


class ResetPasswordRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(..., min_length=8, max_length=128)


# ---------- AUTH ENDPOINTS (username/password) ----------

@app.post("/signup")
def signup(request: SignupRequest):
    if get_user_by_username(request.username):
        raise HTTPException(status_code=400, detail="Username already taken")
    if get_user_by_email(request.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(request.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user_id = str(uuid.uuid4())
    password_hash = hash_password(request.password)
    create_user(user_id, request.username, request.email, password_hash)

    token = create_access_token(user_id, request.username)
    return {"access_token": token, "token_type": "bearer", "username": request.username}


@app.post("/login")
def login(request: LoginRequest):
    user = get_user_by_username(request.username)
    if not user or not user["password_hash"] or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    token = create_access_token(user["id"], user["username"])
    return {"access_token": token, "token_type": "bearer", "username": user["username"]}


# ---------- AUTH ENDPOINT (Google) ----------

@app.post("/auth/google")
def google_login(request: GoogleLoginRequest):
    try:
        idinfo = google_id_token.verify_oauth2_token(
            request.id_token,
            google_requests.Request(),
            os.getenv("GOOGLE_CLIENT_ID")
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_id = idinfo["sub"]
    email = idinfo.get("email", "")
    name = idinfo.get("name", email.split("@")[0] if email else "GoogleUser")

    user = get_user_by_google_id(google_id)

    if user is None:
        user_id = str(uuid.uuid4())
        create_google_user(user_id, name, email, google_id)
        username = name
    else:
        user_id = user["id"]
        username = user["username"]

    token = create_access_token(user_id, username)
    return {"access_token": token, "token_type": "bearer", "username": username}


# ---------- FORGOT PASSWORD / OTP ----------

@app.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest):
    user = get_user_by_username(request.username)
    # Use the same response whether or not the user exists to prevent
    # account enumeration.
    if not user or not user["email"]:
        return {"message": "If this account exists, an OTP has been sent to its registered email."}

    otp = str(random.randint(100000, 999999))
    expires_at = (datetime.now() + timedelta(minutes=10)).isoformat()
    save_otp(request.username, otp, expires_at)

    try:
        send_otp_email(user["email"], otp)
    except Exception as e:
        print(f"[FORGOT PASSWORD] Failed to send email: {e}")
        raise HTTPException(status_code=500, detail="Could not send OTP email. Please try again.")

    return {"message": "If this account exists, an OTP has been sent to its registered email."}


@app.post("/reset-password")
def reset_password(request: ResetPasswordRequest):
    record = get_otp(request.username)

    if record is None:
        raise HTTPException(status_code=400, detail="No OTP request found. Please request a new one.")

    if datetime.now() > datetime.fromisoformat(record["expires_at"]):
        delete_otp(request.username)
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")

    if record["otp"] != request.otp:
        raise HTTPException(status_code=400, detail="Incorrect OTP.")

    if len(request.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    new_hash = hash_password(request.new_password)
    update_user_password(request.username, new_hash)
    delete_otp(request.username)

    return {"message": "Password reset successful. You can now sign in."}


# ---------- HEALTH CHECK ----------

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Incident Response API is running"}


# ---------- PROTECTED ENDPOINTS ----------
# These endpoints require a valid bearer token and scope data by user ID.

@app.post("/analyze")
def analyze_incident(request: LogRequest, current_user: dict = Depends(get_current_user)):
    initial_state = {
        "raw_log": request.raw_log,
        "is_anomaly": None, "anomaly_reason": None,
        "investigation_angles": None, "investigation_findings": [],
        "root_cause": None, "root_cause_confidence": None,
        "suggested_fix": None, "fix_confidence": None,
        "needs_human_review": None, "final_report": None
    }

    result = get_graph_app().invoke(initial_state)

    incident_id = str(uuid.uuid4())
    save_incident(incident_id, current_user["user_id"], result)

    return {
        "id": incident_id,
        "is_anomaly": result["is_anomaly"],
        "anomaly_reason": result["anomaly_reason"],
        "investigation_angles": result["investigation_angles"],
        "investigation_findings": result["investigation_findings"],
        "root_cause": result["root_cause"],
        "root_cause_confidence": result["root_cause_confidence"],
        "suggested_fix": result["suggested_fix"],
        "fix_confidence": result["fix_confidence"],
        "needs_human_review": result["needs_human_review"],
        "final_report": result["final_report"]
    }


@app.get("/incidents")
def list_incidents(current_user: dict = Depends(get_current_user)):
    return get_all_incidents(current_user["user_id"])


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str, current_user: dict = Depends(get_current_user)):
    incident = get_incident_by_id(incident_id, current_user["user_id"])
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@app.get("/incidents/{incident_id}/report")
def download_report(incident_id: str, format: str = "md", current_user: dict = Depends(get_current_user)):
    """
    Return a downloadable report in md, txt, or pdf format.
    The report is generated on demand from database data and is not written to disk.
    """
    incident = get_incident_by_id(incident_id, current_user["user_id"])
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    short_id = incident_id[:8]

    if format == "md":
        content = build_markdown(incident).encode("utf-8")
        media_type, ext = "text/markdown; charset=utf-8", "md"
    elif format == "txt":
        content = build_text(incident).encode("utf-8")
        media_type, ext = "text/plain; charset=utf-8", "txt"
    elif format == "pdf":
        content = build_pdf(incident)
        media_type, ext = "application/pdf", "pdf"
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Use md, txt or pdf.")

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="incident-report-{short_id}.{ext}"'}
    )
