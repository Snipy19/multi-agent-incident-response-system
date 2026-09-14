from graph import app

test_input = {
    "raw_log": "ERROR: Database connection timeout after 30s at checkout-service",
    "is_anomaly": None, "anomaly_reason": None,
    "root_cause": None, "root_cause_confidence": None,
    "suggested_fix": None, "fix_confidence": None,
    "needs_human_review": None, "final_report": None
}

result = app.invoke(test_input)

print("\n\n=== GRAPH FINISHED ===")
print(result["final_report"])