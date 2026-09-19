"""
Ye file prove karti hai ki Orchestrator genuinely DYNAMIC hai -
alag complexity ke logs alag number of investigators spawn karte hain.
Teeno log examples REAL/realistic hain, hardcoded ek jaisa nahi.
"""

from graph import app

test_logs = [
    # Simple - sirf EK issue
    "ERROR: Connection refused to database server 10.0.0.5:5432",

    # Medium - DO issues
    "ERROR: Database connection timeout after 30s at checkout-service. Host also reports high CPU usage at 88%.",

    # Complex - PAANCH+ issues
    "CRITICAL: Multiple failures detected on checkout-service host: database connection timeout (30s), memory usage at 96%, disk I/O latency spiking to 800ms, network packet loss of 12% on eth0, and authentication failures for service account 'db-reader' with 15 failed attempts in last 2 minutes.",
]

for i, log in enumerate(test_logs, 1):
    print(f"\n{'='*80}")
    print(f"TEST {i}: {log[:80]}...")
    print(f"{'='*80}")

    test_input = {
        "raw_log": log,
        "is_anomaly": None, "anomaly_reason": None,
        "investigation_angles": None, "investigation_findings": [],
        "root_cause": None, "root_cause_confidence": None,
        "suggested_fix": None, "fix_confidence": None,
        "needs_human_review": None, "final_report": None
    }

    result = app.invoke(test_input)

    print(f"\n>>> RESULT: {len(result['investigation_findings'])} investigators spawned")
    print(f">>> Angles: {[f['angle'] for f in result['investigation_findings']]}")