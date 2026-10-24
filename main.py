"""
FASTAPI BACKEND (username/password + Google + Forgot Password/OTP + report downloads)
-----------------------------------------------------------------------------------------
The API owns authentication, incident persistence, report downloads, and the
entry point for the LangGraph analysis workflow. The frontend is served at /ui
so local OAuth uses the same origin as the API.
"""

import os
import uuid
import secrets
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field
from typing import Literal, Optional
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from db.database import (
    init_db, save_incident, get_all_incidents, get_incident_by_id,
    create_user, get_user_by_username, get_user_by_email, update_user_password,
    get_user_by_google_id, create_google_user,
    save_otp, get_otp, delete_otp, create_analysis_job, get_analysis_job
)
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    TOKEN_EXPIRE_HOURS,
)
from utils.email_helper import send_otp_email
from utils.report_export import build_markdown, build_text, build_pdf
from utils.evidence import compact_repeated_events
from utils.guardrails import generated_report_input_reason, redact_sensitive_data
from services.analysis_worker import start_analysis_worker


def get_graph_app():
    """Load the expensive LangGraph/RAG pipeline only for a real analysis."""
    # Lazy loading keeps authentication, health checks, report downloads, and
    # CI tests fast without changing the real analysis path.
    from graph import app as graph_app
    return graph_app

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start and stop the durable queue worker with the API process."""
    start_analysis_worker()
    try:
        yield
    finally:
        from services.analysis_worker import stop_analysis_worker
        stop_analysis_worker()


app = FastAPI(title="Autonomous Incident Response API", lifespan=lifespan)

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
    allow_credentials=True,
)

# Serve the frontend from the same origin as the API in local and container
# deployments. This keeps Google OAuth on the configured localhost origin and
# avoids frontend/API port mismatches during development.
app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)


def _set_auth_cookie(response: Response, token: str) -> None:
    """Issue a browser session cookie without removing API bearer tokens."""
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=TOKEN_EXPIRE_HOURS * 60 * 60,
        httponly=True,
        secure=os.getenv("ENVIRONMENT", "development").lower() == "production",
        samesite="lax",
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie("access_token", path="/")


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
):
    # Bearer headers remain supported for CLI/API clients. Browser sessions use
    # the HttpOnly cookie so JavaScript cannot read the JWT directly.
    token = token or request.cookies.get("access_token")
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
    agent_mode: Literal["adaptive", "load_test"] = "adaptive"
    target_agent_count: Optional[int] = Field(default=None, ge=1, le=100)


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


class VerifyOtpRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


def password_policy_error(password: str) -> str | None:
    """Return a user-safe explanation when a password is too weak."""
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return "Password must contain at least one number."
    if not re.search(r"[^A-Za-z0-9\s]", password):
        return "Password must contain at least one special symbol."
    return None


# ---------- AUTH ENDPOINTS (username/password) ----------

@app.post("/signup")
def signup(request: SignupRequest, response: Response):
    if get_user_by_username(request.username):
        raise HTTPException(status_code=400, detail="Username already taken")
    if get_user_by_email(request.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    password_error = password_policy_error(request.password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    user_id = str(uuid.uuid4())
    password_hash = hash_password(request.password)
    create_user(user_id, request.username, request.email, password_hash)

    token = create_access_token(user_id, request.username)
    _set_auth_cookie(response, token)
    return {"access_token": token, "token_type": "bearer", "username": request.username}


@app.post("/login")
def login(request: LoginRequest, response: Response):
    user = get_user_by_username(request.username)
    if not user or not user["password_hash"] or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    token = create_access_token(user["id"], user["username"])
    _set_auth_cookie(response, token)
    return {"access_token": token, "token_type": "bearer", "username": user["username"]}


# ---------- AUTH ENDPOINT (Google) ----------

@app.get("/auth/google/config")
def google_config():
    """Expose only the public Google client ID needed by GIS in the browser."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    return {"enabled": bool(client_id), "client_id": client_id or None}

@app.post("/auth/google")
def google_login(request: GoogleLoginRequest, response: Response):
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        print("[AUTH] Google sign-in rejected: GOOGLE_CLIENT_ID is not configured")
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    try:
        idinfo = google_id_token.verify_oauth2_token(
            request.id_token,
            google_requests.Request(),
            client_id,
            # Small tolerance for normal host/container clock drift. Issuer,
            # audience, signature, and expiry validation remain enabled.
            clock_skew_in_seconds=min(
                max(int(os.getenv("GOOGLE_CLOCK_SKEW_SECONDS", "5")), 0),
                30,
            ),
        )
    except ValueError as exc:
        # Keep token contents out of logs, but record the verifier reason for
        # diagnosing audience, issuer, expiry, or malformed-token problems.
        print(f"[AUTH] Google token verification failed: {exc}")
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_id = idinfo["sub"]
    email = idinfo.get("email", "")
    if not email or not idinfo.get("email_verified", False):
        raise HTTPException(status_code=403, detail="A verified Google email is required")
    name = idinfo.get("name", email.split("@")[0])

    user = get_user_by_google_id(google_id)

    if user is None:
        existing_email_user = get_user_by_email(email)
        if existing_email_user:
            raise HTTPException(
                status_code=409,
                detail="An account already exists for this email. Sign in with that account first.",
            )

        # Display names are not unique and may contain spaces. Use the email
        # local-part as a stable username base, then add a short Google-sub
        # suffix only when another account already uses that name.
        username_base = re.sub(r"[^a-z0-9_]", "", email.split("@", 1)[0].lower())[:24] or "googleuser"
        username = username_base
        if get_user_by_username(username):
            username = f"{username_base[:17]}-{google_id[-6:]}"
        user_id = str(uuid.uuid4())
        create_google_user(user_id, username, email, google_id)
    else:
        user_id = user["id"]
        username = user["username"]

    token = create_access_token(user_id, username)
    _set_auth_cookie(response, token)
    return {"access_token": token, "token_type": "bearer", "username": username}


@app.post("/logout")
def logout(response: Response):
    """End the browser session; bearer tokens remain client-managed."""
    _clear_auth_cookie(response)
    return {"message": "Signed out"}


# ---------- FORGOT PASSWORD / OTP ----------

@app.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest):
    user = get_user_by_username(request.username)
    # This product explicitly confirms the account before moving the user to
    # the OTP step, so the browser never asks for a code that cannot arrive.
    if not user:
        raise HTTPException(status_code=404, detail="No account exists for this username.")
    if not user["email"]:
        raise HTTPException(status_code=400, detail="This account has no recovery email configured.")

    otp = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    save_otp(request.username, otp, expires_at)

    try:
        send_otp_email(user["email"], otp)
    except Exception as e:
        delete_otp(request.username)
        print(f"[FORGOT PASSWORD] Failed to send email: {e}")
        raise HTTPException(status_code=503, detail="Could not send OTP email. Check the configured recovery mailbox and try again.")

    return {"message": "OTP sent to the registered recovery email."}


def _validate_otp(username: str, otp: str):
    record = get_otp(username)
    if record is None:
        raise HTTPException(status_code=400, detail="No OTP request found. Please request a new one.")
    expires_at = datetime.fromisoformat(record["expires_at"])
    if expires_at.tzinfo is None:
        # Preserve compatibility with OTP rows created before UTC timestamps.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        delete_otp(username)
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")
    if not secrets.compare_digest(record["otp"], otp):
        raise HTTPException(status_code=400, detail="Incorrect OTP.")
    return record


@app.post("/verify-reset-otp")
def verify_reset_otp(request: VerifyOtpRequest):
    _validate_otp(request.username, request.otp)
    return {"message": "OTP verified. You may now choose a new password."}


@app.post("/reset-password")
def reset_password(request: ResetPasswordRequest):
    _validate_otp(request.username, request.otp)
    password_error = password_policy_error(request.new_password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

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
    # Validate the request before importing the expensive graph/RAG stack.
    # This keeps invalid API requests fast and prevents CI validation tests
    # from loading the embedding model unnecessarily.
    initial_state = build_initial_state(request)
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
        "root_cause_certainty": result.get("root_cause_certainty"),
        "root_cause_confidence_reason": result.get("root_cause_confidence_reason"),
        "root_cause_evidence": result.get("root_cause_evidence", []),
        "root_cause_missing_evidence": result.get("root_cause_missing_evidence", []),
        "root_cause_alternatives": result.get("root_cause_alternatives", []),
        "suggested_fix": result["suggested_fix"],
        "fix_confidence": result["fix_confidence"],
        "fix_certainty": result.get("fix_certainty"),
        "fix_confidence_reason": result.get("fix_confidence_reason"),
        "fix_evidence": result.get("fix_evidence", []),
        "fix_missing_evidence": result.get("fix_missing_evidence", []),
        "needs_human_review": result["needs_human_review"],
        "final_report": result["final_report"]
    }


@app.post("/analyze/jobs", status_code=202)
def submit_analysis_job(request: LogRequest, current_user: dict = Depends(get_current_user)):
    """Queue an analysis and return immediately with a durable job id."""
    initial_state = build_initial_state(request)
    job_id = str(uuid.uuid4())
    create_analysis_job(job_id, current_user["user_id"], initial_state)
    start_analysis_worker()
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Analysis queued. Poll the job endpoint for completion.",
    }


@app.get("/analyze/jobs/{job_id}")
def analysis_job_status(job_id: str, current_user: dict = Depends(get_current_user)):
    """Return only the authenticated user's job state and final incident id."""
    job = get_analysis_job(job_id, current_user["user_id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    return {
        "job_id": job["id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "events": job["events"],
        "result": job["result"],
        "error": (
            "Analysis failed. Check the service logs or contact an operator."
            if job["status"] == "failed" else None
        ),
    }


def build_initial_state(request: LogRequest) -> dict:
    """Validate mode-specific input and create a sanitized graph state."""
    if request.agent_mode == "load_test" and request.target_agent_count is None:
        raise HTTPException(
            status_code=422,
            detail="target_agent_count is required when agent_mode is load_test",
        )

    report_reason = generated_report_input_reason(request.raw_log)
    if report_reason:
        raise HTTPException(status_code=422, detail=report_reason)

    # Sanitize before the log reaches LangGraph, Groq, RAG, or persistence.
    # The original unredacted payload is deliberately not stored.
    safe_log = redact_sensitive_data(request.raw_log)
    return {
        "raw_log": safe_log,
        "analysis_log": compact_repeated_events(safe_log),
        "agent_mode": request.agent_mode,
        "requested_agent_count": request.target_agent_count,
        "is_anomaly": None, "anomaly_reason": None,
        "investigation_angles": None, "investigation_findings": [],
        "root_cause": None, "root_cause_confidence": None,
        "root_cause_certainty": None, "root_cause_evidence": [],
        "root_cause_missing_evidence": [], "root_cause_alternatives": [],
        "root_cause_confidence_reason": None,
        "suggested_fix": None, "fix_confidence": None,
        "fix_certainty": None, "fix_evidence": [], "fix_missing_evidence": [],
        "fix_confidence_reason": None,
        "needs_human_review": None, "final_report": None
    }


def _sse_event(payload: dict) -> str:
    """Encode one browser-friendly Server-Sent Event."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stage_event(node: str, update: dict) -> dict | None:
    """Translate a LangGraph node update into safe progress text."""
    if node == "investigation_router":
        return None
    messages = {
        "triage_planner": "Triage planner is detecting anomalies and selecting evidence-grounded investigation angles.",
        "aggregator": "Aggregator is comparing investigator evidence and forming a root-cause hypothesis.",
        "fix_suggester": "Remediation agent is evaluating a safe, reviewable recommendation.",
        "report_writer": "Documentation agent is preparing the incident report.",
    }
    if node == "investigator":
        findings = update.get("investigation_findings") or []
        angle = findings[0].get("angle", "unknown angle") if findings else "unknown angle"
        return {
            "type": "investigator",
            "stage": "investigator",
            "message": f"Investigator completed: {angle}.",
            "angle": angle,
        }
    return {
        "type": "stage",
        "stage": node,
        "message": messages.get(node, f"{node.replace('_', ' ').title()} is running."),
    }


@app.post("/analyze/stream")
def stream_analysis(request: LogRequest, current_user: dict = Depends(get_current_user)):
    """Run the real graph while streaming stage updates to the browser."""
    initial_state = build_initial_state(request)

    def event_generator():
        current_state = dict(initial_state)
        current_state["investigation_findings"] = []
        yield _sse_event({
            "type": "start",
            "stage": "started",
            "message": "Analysis started. Preparing the autonomous investigation pipeline.",
        })

        try:
            # LangGraph emits one update as each node completes, including each
            # parallel investigator. No fake progress is generated here.
            for update in get_graph_app().stream(initial_state, stream_mode="updates"):
                for node, node_update in update.items():
                    if not isinstance(node_update, dict):
                        continue
                    if node == "investigator":
                        current_state["investigation_findings"].extend(
                            node_update.get("investigation_findings") or []
                        )
                    current_state.update({
                        key: value
                        for key, value in node_update.items()
                        if key != "investigation_findings"
                    })
                    stage_event = _stage_event(node, node_update)
                    if stage_event:
                        yield _sse_event(stage_event)

            incident_id = str(uuid.uuid4())
            save_incident(incident_id, current_user["user_id"], current_state)
            yield _sse_event({
                "type": "complete",
                "stage": "complete",
                "message": "Analysis complete.",
                "result": {
                    "id": incident_id,
                    "is_anomaly": current_state["is_anomaly"],
                    "anomaly_reason": current_state["anomaly_reason"],
                    "investigation_angles": current_state["investigation_angles"],
                    "investigation_findings": current_state["investigation_findings"],
                    "root_cause": current_state["root_cause"],
                    "root_cause_confidence": current_state["root_cause_confidence"],
                    "root_cause_certainty": current_state.get("root_cause_certainty"),
                    "root_cause_confidence_reason": current_state.get("root_cause_confidence_reason"),
                    "root_cause_evidence": current_state.get("root_cause_evidence", []),
                    "root_cause_missing_evidence": current_state.get("root_cause_missing_evidence", []),
                    "root_cause_alternatives": current_state.get("root_cause_alternatives", []),
                    "suggested_fix": current_state["suggested_fix"],
                    "fix_confidence": current_state["fix_confidence"],
                    "fix_certainty": current_state.get("fix_certainty"),
                    "fix_confidence_reason": current_state.get("fix_confidence_reason"),
                    "fix_evidence": current_state.get("fix_evidence", []),
                    "fix_missing_evidence": current_state.get("fix_missing_evidence", []),
                    "needs_human_review": current_state["needs_human_review"],
                    "final_report": current_state["final_report"],
                },
            })
        except Exception as exc:
            print(f"[STREAM] Analysis failed: {exc}")
            yield _sse_event({
                "type": "error",
                "stage": "error",
                "message": "Analysis failed. Check the service logs for details.",
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
