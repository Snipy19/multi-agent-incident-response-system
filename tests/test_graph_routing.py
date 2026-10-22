"""
EVIDENCE ROUTING TESTS
----------------------
The fan-out planner must give each investigator a focused evidence slice so
large incidents remain useful and affordable to analyze.
"""

from utils.evidence import build_focus_log, compact_repeated_events


def test_focus_log_selects_angle_specific_lines():
    raw_log = "\n".join([
        "service-001 database connection timeout",
        "service-002 kafka consumer lag",
        "service-003 database pool exhausted",
    ])

    focus = build_focus_log(raw_log, "service-002")

    assert "service-002" in focus
    assert "service-001" not in focus


def test_focus_log_has_a_bounded_size():
    raw_log = "\n".join(f"service-{index:03d} ERROR repeated failure" for index in range(5000))

    assert len(build_focus_log(raw_log, "database", max_chars=8000)) <= 8000


def test_focus_log_uses_component_aliases_for_messaging():
    raw_log = "\n".join([
        "checkout-api returned HTTP 503",
        "Kafka consumer lag increased to 31000 messages",
        "PostgreSQL connection timed out",
    ])

    focus = build_focus_log(raw_log, "Messaging")

    assert "Kafka consumer lag" in focus
    assert "PostgreSQL connection" not in focus


def test_compact_repeated_events_preserves_count_and_order():
    raw_log = "\n".join([
        "2026-10-22T19:00:00Z ERROR checkout timeout",
        "2026-10-22T19:00:01Z ERROR checkout timeout",
        "2026-10-22T19:00:02Z ERROR checkout timeout",
        "2026-10-22T19:00:03Z WARN cache latency",
    ])

    compacted = compact_repeated_events(raw_log)

    assert "[repeated event x3]" in compacted
    assert compacted.index("checkout timeout") < compacted.index("cache latency")
    assert "2026-10-22T19:00:00Z" in compacted
