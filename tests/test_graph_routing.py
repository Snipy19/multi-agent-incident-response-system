"""
EVIDENCE ROUTING TESTS
----------------------
The fan-out planner must give each investigator a focused evidence slice so
large incidents remain useful and affordable to analyze.
"""

from utils.evidence import build_focus_log


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
