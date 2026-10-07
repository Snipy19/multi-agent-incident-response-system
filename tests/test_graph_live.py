import os

import pytest


pytestmark = pytest.mark.live

if os.getenv("RUN_LIVE_LLM_TESTS") != "1":
    pytest.skip(
        "Live tests are disabled. Set RUN_LIVE_LLM_TESTS=1 to call Groq and the real RAG index.",
        allow_module_level=True,
    )


from graph import app  # noqa: E402

# These tests intentionally call the real Groq and RAG stack. They are opt-in
# because they require credentials, network access, time, and API quota.


def initial_state(raw_log: str) -> dict:
    return {
        "raw_log": raw_log,
        "is_anomaly": None,
        "anomaly_reason": None,
        "investigation_angles": None,
        "investigation_findings": [],
        "root_cause": None,
        "root_cause_confidence": None,
        "suggested_fix": None,
        "fix_confidence": None,
        "needs_human_review": None,
        "final_report": None,
    }


def test_real_pipeline_detects_and_analyzes_incident():
    result = app.invoke(
        initial_state(
            "CRITICAL: checkout-service database connection timeout after 30s; "
            "memory usage is 96% and disk I/O latency is 800ms."
        )
    )

    assert result["is_anomaly"] is True
    assert result["anomaly_reason"]
    assert result["investigation_angles"]
    assert len(result["investigation_findings"]) == len(result["investigation_angles"])
    assert all(f["angle"] for f in result["investigation_findings"])
    assert all(isinstance(f["finding"], str) and f["finding"] for f in result["investigation_findings"])
    assert all(0 <= f["confidence"] <= 1 for f in result["investigation_findings"])
    assert result["root_cause"]
    assert 0 <= result["root_cause_confidence"] <= 1
    assert result["suggested_fix"]
    assert 0 <= result["fix_confidence"] <= 1
    assert isinstance(result["needs_human_review"], bool)
    assert result["final_report"]


def test_real_pipeline_stops_without_investigators_for_normal_log():
    result = app.invoke(initial_state("INFO: scheduled health check completed successfully"))

    assert result["is_anomaly"] is False
    assert result["investigation_findings"] == []
    assert result["final_report"] is None
