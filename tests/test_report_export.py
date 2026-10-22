from utils.report_export import _now, _when, build_live_report, build_markdown, build_pdf, build_text


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


def test_report_timestamps_display_in_india_time():
    assert _when("2026-10-22T12:05:00") == "22 Oct 2026, 05:35 PM"
    assert _when("2026-10-22T12:05:00+00:00") == "22 Oct 2026, 05:35 PM"
    assert _now()


def test_live_report_is_structured_without_inventing_claims():
    incident = sample_incident()
    incident.update({
        "root_cause_certainty": "Strong hypothesis",
        "root_cause_evidence": ["The database endpoint timed out."],
        "root_cause_missing_evidence": ["Network reachability test"],
        "root_cause_alternatives": ["Connection-pool exhaustion"],
        "fix_certainty": "Inconclusive",
        "fix_evidence": ["The timeout is directly observed."],
        "fix_missing_evidence": ["Validate database health first."],
    })

    report = build_live_report(incident)

    assert "Strong hypothesis" in report
    assert "Network reachability test" in report
    assert "Connection-pool exhaustion" in report
    assert "The fix was applied" not in report


def test_report_formats_normalize_problematic_typography():
    incident = sample_incident()
    incident["root_cause"] = "Network‑level failure — service’s connection was rejected."

    markdown = build_markdown(incident)
    text = build_text(incident)

    assert "Network-level failure - service's connection was rejected." in markdown
    assert "Network-level failure - service's connection was rejected." in text


def test_report_formats_repair_common_stored_mojibake():
    incident = sample_incident()
    incident["root_cause"] = (
        "Service" + chr(0x00e2) + chr(0x20ac) + chr(0x2122) + "s network"
        + chr(0x00e2) + chr(0x20ac) + chr(0x2018) + "level check failed "
        + chr(0x00e2) + chr(0x20ac) + chr(0x201d) + " retry required."
    )

    markdown = build_markdown(incident)
    text = build_text(incident)

    assert "Service" in markdown and "network-level" in markdown
    assert "retry required." in markdown
    assert "Service" in text and "network-level" in text
    assert "retry required." in text
    assert "â" not in markdown
    assert "â" not in text
