from utils.guardrails import calibrate_confidence, parse_investigator_output, redact_sensitive_data


def test_redacts_common_credentials_and_personal_data():
    raw_log = (
        "Authorization: Bearer abc123 password=hunter2 "
        "api_key=gsk_test_1234567890 user=person@example.com"
    )

    sanitized = redact_sensitive_data(raw_log)

    assert "abc123" not in sanitized
    assert "hunter2" not in sanitized
    assert "gsk_test_1234567890" not in sanitized
    assert "person@example.com" not in sanitized
    assert "[REDACTED" in sanitized


def test_invalid_investigator_json_is_safe_low_confidence():
    finding = parse_investigator_output("not json", "Database", "database timeout")

    assert finding["angle"] == "Database"
    assert finding["confidence"] == 0.0


def test_unsupported_finding_is_confidence_capped():
    finding = parse_investigator_output(
        '{"finding":"The CDN certificate is expired.","confidence":0.98}',
        "Database",
        "PostgreSQL connection timeout on port 5432",
    )

    assert finding["confidence"] == 0.35
    assert "does not directly support" in finding["finding"]


def test_supported_finding_preserves_valid_confidence():
    finding = parse_investigator_output(
        '{"finding":"PostgreSQL connection timeout indicates database connectivity trouble.","confidence":0.84}',
        "Database",
        "checkout-service PostgreSQL connection timeout after 30s",
    )

    assert finding["confidence"] == 0.84


def test_calibration_uses_agreement_and_evidence_breadth():
    calibrated = calibrate_confidence(0.95, [0.90, 0.80], 2)

    # Two supporting angles should produce a conservative score below the
    # model's self-reported 95%, rather than displaying it unchanged.
    assert calibrated == 0.86


def test_calibration_penalizes_operational_fix_risk():
    calibrated = calibrate_confidence(0.95, [0.84], 1, risk_penalty=0.05)

    assert calibrated == 0.74
