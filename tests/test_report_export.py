from utils.report_export import build_markdown, build_pdf, build_text


def sample_incident():
    # Reports should be reproducible from stored structured incident data.
    return {
        "id": "incident-test-1234",
        "created_at": "2026-10-07T10:00:00",
        "raw_log": "ERROR: Database connection timeout after 30s",
        "is_anomaly": True,
        "anomaly_reason": "A database connection timed out.",
        "investigation_angles": ["Database"],
        "investigation_findings": [
            {
                "angle": "Database",
                "finding": "The database endpoint did not respond within the timeout window.",
                "confidence": 0.91,
            }
        ],
        "root_cause": "The database service was unavailable or unreachable.",
        "root_cause_confidence": 0.82,
        "suggested_fix": "Check database health and restore connectivity before retrying traffic.",
        "fix_confidence": 0.78,
        "needs_human_review": False,
        "final_report": "A real incident report.",
    }


def test_report_formats_are_built_from_incident_data():
    incident = sample_incident()

    markdown = build_markdown(incident)
    text = build_text(incident)
    pdf = build_pdf(incident)

    assert "incident-test-1234" in markdown
    assert "Database" in markdown
    assert "incident-test-1234" in text
    assert "A database connection" in text
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_report_formats_normalize_problematic_typography():
    incident = sample_incident()
    incident["root_cause"] = "Network‑level failure — service’s connection was rejected."

    markdown = build_markdown(incident)
    text = build_text(incident)

    assert "Network-level failure - service's connection was rejected." in markdown
    assert "Network-level failure - service's connection was rejected." in text
    assert "â" not in markdown
    assert "â" not in text
