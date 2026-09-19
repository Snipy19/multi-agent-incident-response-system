from state import IncidentState
from agents.log_monitor import log_monitor_agent
from agents.orchestrator import orchestrator_agent

test_state: IncidentState = {
    "raw_log": "ERROR: Database connection timeout after 30s at checkout-service, also observed high memory usage (95%) and slow disk I/O on the host",
    "is_anomaly": None, "anomaly_reason": None,
    "investigation_angles": None, "investigation_findings": [],
    "root_cause": None, "root_cause_confidence": None,
    "suggested_fix": None, "fix_confidence": None,
    "needs_human_review": None, "final_report": None
}

state = log_monitor_agent(test_state)
state = orchestrator_agent(state)

print("\n--- ANGLES DECIDED ---")
print(state["investigation_angles"])