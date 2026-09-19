"""
FASTAPI BACKEND
------------------
Kaam: Hamare LangGraph pipeline ko ek web API bana dena, taaki
frontend (ya koi bhi client) HTTP request bhej ke incident analyze kar sake.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from graph import app as graph_app

app = FastAPI(title="Autonomous Incident Response API")

# CORS: taaki browser mein chalne wala frontend (alag port pe) is API ko
# call kar sake. Bina isके, browser security reasons se request block kar deta.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # abhi ke liye sabko allow, production mein specific domain daalenge
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request body ka shape define karte hain - client isi format mein
# data bhejega
class LogRequest(BaseModel):
    raw_log: str


@app.get("/")
def health_check():
    """Simple endpoint check karne ke liye ki server chal raha hai"""
    return {"status": "ok", "message": "Incident Response API is running"}


@app.post("/analyze")
def analyze_incident(request: LogRequest):
    """
    Main endpoint - client ek log bhejta hai, hum poora LangGraph
    pipeline chalate hain aur result wapas dete hain.
    """
    initial_state = {
        "raw_log": request.raw_log,
        "is_anomaly": None, "anomaly_reason": None,
        "investigation_angles": None, "investigation_findings": [],
        "root_cause": None, "root_cause_confidence": None,
        "suggested_fix": None, "fix_confidence": None,
        "needs_human_review": None, "final_report": None
    }

    result = graph_app.invoke(initial_state)

    # Sirf zaroori fields wapas bhejte hain, poora internal state nahi
    return {
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