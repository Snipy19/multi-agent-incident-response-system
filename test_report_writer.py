from state import IncidentState
from agents.log_monitor import log_monitor_agent
from agents.root_cause_analyzer import root_cause_analyzer_agent
from agents.fix_suggester import fix_suggester_agent
from agents.report_writer import report_writer_agent

test_state: IncidentState = {
    "raw_log": "ERROR: Database connection timeout after 30s at checkout-service",
    "is_anomaly": None, "anomaly_reason": None,
    "root_cause": None, "root_cause_confidence": None,
    "suggested_fix": None, "fix_confidence": None,
    "needs_human_review": None, "final_report": None
}

state = log_monitor_agent(test_state)
state = root_cause_analyzer_agent(state)
state = fix_suggester_agent(state)
state = report_writer_agent(state)

print("\n--- FINAL REPORT ---")
print(state["final_report"])