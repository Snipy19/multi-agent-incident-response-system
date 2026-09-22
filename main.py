"""
FASTAPI BACKEND
------------------
Kaam: Hamare LangGraph pipeline ko ek web API bana dena, taaki
frontend (ya koi bhi client) HTTP request bhej ke incident analyze kar sake.

Ab isme database integration bhi hai - har incident SQLite mein
save hota hai, aur past incidents ki list bhi fetch kar sakte hain.
"""

import uuid
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from graph import app as graph_app
from db.database import init_db, save_incident, get_all_incidents, get_incident_by_id

app = FastAPI(title="Autonomous Incident Response API")

# Database table ready karo agar exist nahi karti
init_db()

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
    pipeline chalate hain, result ko database mein save karte hain,
    aur result wapas dete hain.
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

    # Ek unique ID banate hain iss incident ke liye, aur database mein save karte hain
    incident_id = str(uuid.uuid4())
    save_incident(incident_id, result)

    # Sirf zaroori fields wapas bhejte hain, poora internal state nahi
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
def list_incidents():
    """Sab past incidents ki summary list deta hai, sabse naya pehle"""
    return get_all_incidents()


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    """Ek specific incident ka poora detail deta hai, uski ID se"""
    incident = get_incident_by_id(incident_id)
    if incident is None:
        return {"error": "Incident not found"}
    return incident