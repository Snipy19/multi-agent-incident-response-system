"""
EVIDENCE ROUTING HELPERS
------------------------
Small, dependency-free helpers used to give each investigator only the log
lines relevant to its assigned angle.
"""


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
