"""
AGENT PLANNING HELPERS
----------------------
Dependency-free target planning logic. Keeping this separate from the Groq
client lets CI test fan-out behavior without requiring an API key.
"""

import os
import re


MAX_AGENT_COUNT = int(os.getenv("MAX_AGENT_COUNT", "100"))


def named_service_targets(raw_log: str) -> list[str]:
    """Extract explicit service identifiers while preserving their order."""
    matches = re.findall(r"\bservice[-_]\d+\b", raw_log, flags=re.IGNORECASE)
    return list(dict.fromkeys(matches))


def deduplicate_angles(angles: list[str], max_count: int = MAX_AGENT_COUNT) -> list[str]:
    """Remove repeated labels while preserving the model's evidence order."""
    unique = []
    seen = set()
    for angle in angles:
        label = str(angle).strip()
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            unique.append(label)
    return unique[:max_count]


def ensure_failure_domain_coverage(raw_log: str, angles: list[str]) -> list[str]:
    """Add only explicit, independently failing domains omitted by the LLM.

    This is a coverage guardrail, not one-agent-per-line routing. A domain is
    added only when the log names its component and reports a failure signal.
    """
    text = raw_log.casefold()
    result = deduplicate_angles(angles)

    domains = (
        ("Database", ("postgres", "mysql", "database", "db-"), ("timeout", "failed", "error", "unavailable")),
        ("Cache", ("redis", "cache"), ("latency", "timeout", "failed", "error", "stale")),
        ("Messaging", ("kafka", "consumer", "queue", "message"), ("lag", "rebalance", "failed", "error", "timeout")),
        ("Network", ("dns", "packet loss", "routing", "firewall", "network"), ("failed", "timeout", "loss", "latency", "error")),
        ("Application", ("api", "service", "pod", "readiness", "http 5"), ("error", "failed", "timeout", "503", "restarted", "latency")),
    )

    for label, names, signals in domains:
        named = any(name in text for name in names)
        failing = any(signal in text for signal in signals)
        already_covered = any(
            label.casefold() in angle.casefold()
            or any(alias in angle.casefold() for alias in names)
            for angle in result
        )
        if named and failing and not already_covered:
            result.append(label)
    return deduplicate_angles(result)


def requested_load_test_targets(raw_log: str, requested_count: int) -> list[str]:
    """Create exactly the requested number of explicit load-test targets."""
    targets = named_service_targets(raw_log)[:requested_count]
    targets.extend(
        f"load-test-agent-{index:03d}"
        for index in range(len(targets) + 1, requested_count + 1)
    )
    return targets
