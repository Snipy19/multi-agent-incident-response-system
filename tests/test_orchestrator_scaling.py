"""
SCALABLE FAN-OUT TESTS
----------------------
Verify that the orchestrator can preserve explicit service targets and create
an exact requested count in the dedicated load-test mode.
"""

from utils.agent_planning import named_service_targets, requested_load_test_targets


def test_named_services_are_deduplicated_in_input_order():
    log = "service-002 ERROR; service-001 WARN; service-002 CRITICAL"

    assert named_service_targets(log) == ["service-002", "service-001"]


def test_load_test_mode_creates_exact_requested_count():
    log = "service-001 ERROR service-002 WARN service-003 CRITICAL"

    targets = requested_load_test_targets(log, 10)

    assert len(targets) == 10
    assert targets[:3] == ["service-001", "service-002", "service-003"]
    assert targets[-1] == "load-test-agent-010"
