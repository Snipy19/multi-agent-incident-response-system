from graph import app

test_input = {
    "raw_log": "ERROR: Database connection timeout after 30s at checkout-service, also observed high memory usage (95%) and slow disk I/O on the host",
    "is_anomaly": None, "anomaly_reason": None,
    "investigation_angles": None, "investigation_findings": [],
    "root_cause": None, "root_cause_confidence": None,
    "suggested_fix": None, "fix_confidence": None,
    "needs_human_review": None, "final_report": None
}

result = app.invoke(test_input)

print("\n\n=== GRAPH FINISHED ===")
print(f"\nTotal investigators spawned: {len(result['investigation_findings'])}")
for f in result['investigation_findings']:
    print(f"  - [{f['angle']}] {f['finding']}")
print(f"\n{result['final_report']}")