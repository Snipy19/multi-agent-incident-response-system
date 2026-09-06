from state import IncidentState
from agents.log_monitor import log_monitor_agent

test_state: IncidentState = {
    "raw_log": "ERROR: Database connection timeout after 30s at checkout-service",
    "is_anomaly": None, "anomaly_reason": None,
    "root_cause": None, "root_cause_confidence": None,
    "suggested_fix": None, "fix_confidence": None,
    "needs_human_review": None, "final_report": None
}

result = log_monitor_agent(test_state)
print("\n--- FINAL RESULT ---")
print(result)