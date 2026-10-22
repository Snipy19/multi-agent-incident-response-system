"""
EVIDENCE ROUTING HELPERS
------------------------
Small, dependency-free helpers used to give each investigator only the log
lines relevant to its assigned angle.
"""

import re


_TIMESTAMP_PREFIX = re.compile(
    r"^\s*(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\s+|\[[^\]]+\]\s+)"
)


def compact_repeated_events(raw_log: str, max_chars: int = 24000) -> str:
    """Collapse repeated log events while preserving counts and order.

    The original log is never changed or persisted through this helper. The
    compact view is only used for LLM analysis so large repeated bursts do not
    consume the context window repeatedly.
    """
    lines = str(raw_log or "").splitlines()
    if not lines:
        return str(raw_log or "")[:max_chars]

    output = []
    previous_key = None
    previous_line = None
    repeat_count = 0

    def flush():
        nonlocal previous_key, previous_line, repeat_count
        if previous_line is None:
            return
        output.append(previous_line)
        if repeat_count > 1:
            output.append(f"[repeated event x{repeat_count}]")
        previous_key = previous_line = None
        repeat_count = 0

    for line in lines:
        normalized = _TIMESTAMP_PREFIX.sub("", line).strip()
        key = normalized.casefold()
        if key and key == previous_key:
            repeat_count += 1
            continue
        flush()
        previous_key = key
        previous_line = line
        repeat_count = 1
    flush()

    compacted = "\n".join(output)
    if len(compacted) <= max_chars:
        return compacted
    head_size = max_chars * 2 // 3
    tail_size = max_chars - head_size
    return compacted[:head_size] + "\n[... middle of compacted log omitted ...]\n" + compacted[-tail_size:]


def build_focus_log(raw_log: str, angle: str, max_chars: int = 8000) -> str:
    """Return angle-specific evidence without loading the RAG stack."""
    lines = raw_log.splitlines()
    if not lines:
        return raw_log[:max_chars]

    keywords = [word.lower() for word in angle.replace("_", "-").split() if len(word) > 2]
    relevant = [
        line for line in lines
        if any(keyword in line.lower() for keyword in keywords)
    ]
    selected = relevant or lines[:40]
    return "\n".join(selected)[:max_chars]
