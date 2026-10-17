"""
INPUT AND LLM GUARDRAILS
------------------------
Small, dependency-free protections that run before data reaches the LLMs.
These are intentionally deterministic so they remain testable and work in
local development, CI, Docker, and AWS without another service.
"""

import json
import re
from typing import Any, Iterable

CERTAINTY_LEVELS = {"Confirmed", "Strong hypothesis", "Inconclusive"}


_SECRET_PATTERNS = (
    # Common bearer credentials and cloud/API key formats.
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\b(?:gsk_|sk-|xox[baprs]-)[A-Za-z0-9_\-/]{12,}\b"), "[REDACTED_API_KEY]"),
    # JWT-like values are safe to redact without attempting to decode them.
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "[REDACTED_JWT]"),
    # Key/value secrets in common log formats: password=..., api_key: ... .
    (
        re.compile(
            r"(?i)(\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[=:]\s*)[^\s,;]+"
        ),
        r"\1[REDACTED_SECRET]",
    ),
    # Email addresses are not required for technical diagnosis.
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[REDACTED_EMAIL]"),
)


def redact_sensitive_data(raw_log: str) -> str:
    """Return a log safe to send to an LLM and persist in the database."""
    sanitized = raw_log
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def parse_investigator_output(raw_output: str, angle: str, evidence: str) -> dict[str, Any]:
    """Validate and ground one investigator's JSON response.

    Invalid model output becomes a safe low-confidence finding instead of
    crashing a parallel fan-out. A finding with no meaningful overlap with its
    evidence is retained for auditability but its confidence is capped.
    """
    fallback = {
        "angle": angle,
        "finding": f"{angle} analysis was inconclusive because the model response was invalid.",
        "confidence": 0.0,
        "certainty": "Inconclusive",
        "supporting_evidence": [],
        "missing_evidence": ["A valid investigator response"],
        "alternatives": [],
    }

    try:
        parsed = json.loads(raw_output)
        if not isinstance(parsed, dict):
            return fallback

        finding = parsed.get("finding")
        confidence = parsed.get("confidence")
        if not isinstance(finding, str) or not finding.strip() or len(finding) > 2000:
            return fallback
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return fallback
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            return fallback
    except (json.JSONDecodeError, TypeError, ValueError):
        return fallback

    if not _has_evidence_overlap(finding, evidence):
        confidence = min(confidence, 0.35)
        finding = (
            f"The available log evidence does not directly support a confident "
            f"{angle} conclusion. Model note: {finding}"
        )

    certainty = parsed.get("certainty", "Inconclusive")
    if certainty not in CERTAINTY_LEVELS:
        certainty = "Inconclusive"

    def clean_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()][:5]

    return {
        "angle": angle,
        "finding": finding.strip(),
        "confidence": round(confidence, 2),
        "certainty": certainty,
        "supporting_evidence": clean_list(parsed.get("supporting_evidence")),
        "missing_evidence": clean_list(parsed.get("missing_evidence")),
        "alternatives": clean_list(parsed.get("alternatives")),
    }


def calibrate_confidence(
    model_confidence: float,
    supporting_confidences: Iterable[float],
    independent_angle_count: int,
    risk_penalty: float = 0.0,
) -> float:
    """Convert a model estimate into a more conservative workflow score.

    LLM self-reported confidence is not a calibrated probability. This score
    combines it with investigator agreement and evidence breadth, then applies
    an optional operational-risk penalty for remediation recommendations.
    """
    model = min(max(float(model_confidence), 0.0), 1.0)
    supporting = [min(max(float(value), 0.0), 1.0) for value in supporting_confidences]
    agreement = sum(supporting) / len(supporting) if supporting else 0.0
    breadth = min(max(independent_angle_count, 0) / 3.0, 1.0)
    calibrated = (0.45 * model) + (0.35 * agreement) + (0.20 * breadth)
    calibrated -= min(max(float(risk_penalty), 0.0), 0.25)
    return round(min(max(calibrated, 0.0), 1.0), 2)


def _has_evidence_overlap(finding: str, evidence: str) -> bool:
    """Require at least one meaningful technical term from the evidence."""
    stop_words = {
        "about", "after", "also", "could", "from", "into", "that", "their",
        "there", "these", "this", "with", "which", "would", "likely", "indicate",
        "indicating", "suggest", "suggests", "issue", "issues", "problem", "problems",
    }
    evidence_words = {
        word.lower()
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{2,}", evidence)
        if word.lower() not in stop_words
    }
    finding_words = {
        word.lower()
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{2,}", finding)
        if word.lower() not in stop_words
    }
    return bool(evidence_words & finding_words)
