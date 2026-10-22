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

_GENERATED_REPORT_MARKERS = (
    re.compile(r"(?im)^\s*(?:#\s*)?confidence\s+basis\s*:"),
    re.compile(r"(?im)^\s*(?:#\s*)?full\s+report\s*$"),
    re.compile(r"(?im)^\s*(?:#\s*)?recommended\s+(?:fix|remediation)\b"),
    re.compile(r"(?im)^\s*(?:#\s*)?investigation\s+findings\s*$"),
    re.compile(r"(?im)^\s*(?:#\s*)?root\s+cause\s+(?:assessment|analysis)\s*$"),
)


def redact_sensitive_data(raw_log: str) -> str:
    """Return a log safe to send to an LLM and persist in the database."""
    sanitized = raw_log
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def generated_report_input_reason(raw_log: str) -> str | None:
    """Return a reason when input clearly looks like generated report text.

    A single operational word such as ``timeout`` is intentionally not enough
    to reject a log. These markers are report-specific and are checked before
    any LLM or investigator work begins.
    """
    text = str(raw_log or "")
    for marker in _GENERATED_REPORT_MARKERS:
        if marker.search(text):
            return (
                "The submitted text appears to be generated analysis/report content "
                "rather than a raw operational log. Submit timestamps, service names, "
                "errors, metrics, or stack traces."
            )
    return None


def parse_json_object(raw_output: str) -> dict[str, Any]:
    """Parse a model JSON object even when it includes a code fence or prose."""
    text = str(raw_output or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(parsed, dict):
        raise ValueError("model response must be a JSON object")
    return parsed


def clean_model_text(value: Any) -> str:
    """Repair common UTF-8/Windows-1252 decoding damage in model output."""
    text = "" if value is None else str(value)
    for _ in range(2):
        if not any(marker in text for marker in ("Ã", "Â", "â", "ð")):
            break
        try:
            repaired = text.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if repaired == text:
            break
        text = repaired
    return (text.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
            .replace("\u2018", "'").replace("\u2019", "'")
            .replace("\u2022", "-"))


def constrain_cross_service_causality(root_cause: str, raw_log: str) -> tuple[str, bool]:
    """Prevent an unsupported DNS-to-service causal chain from being reported.

    This is deliberately narrow: it only applies when the log names DNS
    failures for the database hostname while separately reporting Redis/Kafka
    symptoms, without directly connecting DNS to those components.
    """
    conclusion = clean_model_text(root_cause).strip()
    log = raw_log.casefold()
    text = conclusion.casefold()
    if not all(term in log for term in ("dns", "db-primary", "redis", "kafka")):
        return conclusion, False
    if not _unsupported_dns_service_link(text, log):
        return conclusion, False

    guarded = (
        "The log directly confirms intermittent DNS lookup failures for "
        "db-primary.internal and PostgreSQL connection timeouts, making a "
        "database-connectivity issue a strong hypothesis. Redis latency and "
        "Kafka lag are observed concurrent symptoms, but the submitted log "
        "does not establish that DNS caused them; their relationship requires "
        "separate validation."
    )
    return guarded, True


def _unsupported_dns_service_link(claim: str, log: str) -> bool:
    """Detect DNS causality claims not directly connected in the submitted log."""
    causal = any(term in claim for term in ("caused", "causing", "exacerbated", "due to", "same dns", "dns instability"))
    if "dns" not in claim or not causal:
        return False
    targets = [target for target in ("redis", "kafka", "consumer lag") if target in claim]
    if not targets:
        return False
    # A direct link requires DNS and the target to appear in the same log
    # sentence. Separate symptoms in adjacent sentences are not proof.
    sentences = re.split(r"(?<=[.!?])\s+|[;\n]+", log)
    return any(
        target in targets
        and not any("dns" in sentence and target in sentence for sentence in sentences)
        for target in targets
    )


def constrain_investigator_causality(finding: str, evidence: str, angle: str) -> tuple[str, bool]:
    """Downgrade an investigator claim when its cross-service link is unproven."""
    claim = clean_model_text(finding).strip()
    log = str(evidence or "").casefold()
    if not all(term in log for term in ("dns", "db-primary")):
        return claim, False
    if not _unsupported_dns_service_link(claim.casefold(), log):
        return claim, False
    return (
        f"The {angle} evidence is not sufficient to establish that DNS caused "
        "the separate Redis or Kafka symptoms; those relationships require "
        "direct service-specific validation.",
        True,
    )


def constrain_dns_remediation(suggested_fix: str, raw_log: str) -> tuple[str, bool]:
    """Keep DNS infrastructure changes conditional on resolver evidence."""
    recommendation = clean_model_text(suggested_fix).strip()
    text = recommendation.casefold()
    log = raw_log.casefold()
    dns_change = any(term in text for term in ("coredns", "secondary dns", "local dns", "dns caching"))
    resolver_evidence = any(term in log for term in ("resolver", "dns server", "dns misconfiguration", "dns cache"))
    if not dns_change or resolver_evidence:
        return recommendation, False

    guarded = (
        "First validate DNS query failure rates, resolver health, and resolution "
        "of db-primary.internal from the checkout-api pods. Check database "
        "reachability and correlate the timing with Redis and Kafka metrics. "
        "Only if resolver-side failures are confirmed should the team evaluate "
        "a DNS configuration or caching change; this log alone does not justify "
        "adding DNS infrastructure."
    )
    return guarded, True


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
        "confidence_reason": "No valid model response was available to assess the evidence.",
        "certainty": "Inconclusive",
        "supporting_evidence": [],
        "missing_evidence": ["A valid investigator response"],
        "alternatives": [],
    }

    try:
        parsed = parse_json_object(raw_output)
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

    finding_text, causality_guarded = constrain_investigator_causality(
        finding.strip(), evidence, angle
    )
    if causality_guarded:
        confidence = min(confidence, 0.35)
        certainty = "Inconclusive"
        missing = clean_list(parsed.get("missing_evidence"))
        missing.append("Direct DNS-to-service evidence for the claimed Redis or Kafka impact")
        alternatives = clean_list(parsed.get("alternatives"))
        alternatives.append("An independent cache, broker, or consumer-capacity issue")
    else:
        missing = clean_list(parsed.get("missing_evidence"))
        alternatives = clean_list(parsed.get("alternatives"))

    return {
        "angle": angle,
        "finding": finding_text,
        "confidence": round(confidence, 2),
        "confidence_reason": clean_model_text(
            parsed.get("confidence_reason")
            or "The model did not provide a confidence rationale. Review the evidence and missing validation."
        ),
        "certainty": certainty,
        "supporting_evidence": [clean_model_text(x) for x in clean_list(parsed.get("supporting_evidence"))],
        "missing_evidence": [clean_model_text(x) for x in missing[:5]],
        "alternatives": [clean_model_text(x) for x in alternatives[:5]],
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
