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


def requested_load_test_targets(raw_log: str, requested_count: int) -> list[str]:
    """Create exactly the requested number of explicit load-test targets."""
    targets = named_service_targets(raw_log)[:requested_count]
    targets.extend(
        f"load-test-agent-{index:03d}"
        for index in range(len(targets) + 1, requested_count + 1)
    )
    return targets
