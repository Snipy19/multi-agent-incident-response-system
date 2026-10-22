"""
FIX SUGGESTER AGENT
"""

import os
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState
from utils.llm_helper import invoke_with_retry
from utils.guardrails import (
    CERTAINTY_LEVELS,
    clean_model_text,
    constrain_dns_remediation,
    parse_json_object,
)

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=2048,
    reasoning_effort="low",
    api_key=os.getenv("GROQ_API_KEY")
)

CONFIDENCE_THRESHOLD = 0.5


def fix_suggester_agent(state: IncidentState) -> IncidentState:
    # Remediation is advisory only. Low-confidence and broad/critical cases
    # are escalated instead of being treated as safe for automatic action.
    print("\n[FIX SUGGESTER AGENT] Preparing a remediation recommendation...")

    root_cause_confidence = state["root_cause_confidence"]

    # Broad incidents are never safe to auto-approve solely from an LLM
    # confidence score. Escalate them so an engineer reviews the diagnosis
    # before any remediation is applied.
    angle_count = len(state.get("investigation_angles") or [])
    is_critical_log = "critical" in state.get("raw_log", "").lower()
    requires_human_review = angle_count >= 10 or is_critical_log

    if root_cause_confidence < CONFIDENCE_THRESHOLD:
        print(f"[FIX SUGGESTER AGENT] Confidence is too low ({root_cause_confidence}); human review is required")
        state["suggested_fix"] = "No remediation was recommended because confidence was too low."
        state["fix_confidence"] = 0.0
        state["fix_certainty"] = "Inconclusive"
        state["fix_evidence"] = []
        state["fix_missing_evidence"] = ["A sufficiently supported root cause"]
        state["needs_human_review"] = True
        return {k: v for k, v in state.items() if k != "investigation_findings"}

    root_cause = state["root_cause"]
    raw_log = state["raw_log"]
    root_cause_evidence = state.get("root_cause_evidence") or []
    missing_evidence = state.get("root_cause_missing_evidence") or []
    alternatives = state.get("root_cause_alternatives") or []

    prompt = f"""You are a senior DevOps engineer. Based on the following root cause analysis, suggest a specific, actionable fix.

Root cause:
"{root_cause}"

Original submitted log (the only direct incident evidence):
{raw_log}

Root-cause supporting evidence:
{root_cause_evidence}

Root-cause missing validation:
{missing_evidence}

Competing explanations:
{alternatives}

Do not present a numeric score as a calibrated probability. Select one certainty
level exactly: Confirmed, Strong hypothesis, or Inconclusive. A fix is never
confirmed merely because the diagnosis is plausible; say what must be validated
before applying it and avoid destructive or irreversible actions. Prefer the
least-invasive validation steps first, such as checking DNS queries, service
discovery logs, health metrics, connection-pool state, and packet reachability.
Do not propose adding a service mesh, sidecar, cache layer, replica pool, or
other new infrastructure unless the submitted evidence directly shows that the
existing component is misconfigured or capacity-constrained. Do not treat a
timeout as proof of a DNS, firewall, or network root cause.
Do not recommend a fix for a secondary symptom as if it resolves the primary
incident. If the evidence cannot identify one cause, recommend diagnostic and
containment steps instead of a permanent architecture change. Each proposed
action must state what observation would justify applying it.

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "suggested_fix": "a concise, specific, actionable fix (2-3 sentences)",
    "confidence": 0.0 to 1.0,
    "confidence_reason": "one sentence explaining why the evidence supports this remediation and what uncertainty remains",
    "certainty": "Confirmed | Strong hypothesis | Inconclusive",
    "supporting_evidence": ["facts supporting why this fix addresses the issue"],
    "missing_evidence": ["validation required before applying the fix"]
}}"""

    response = invoke_with_retry(llm, prompt)
    raw_output = response.content.strip()

    print(f"[FIX SUGGESTER AGENT] LLM ka raw output: {raw_output}")

    try:
        parsed = parse_json_object(raw_output)
        suggested_fix = clean_model_text(parsed["suggested_fix"])
        model_confidence = float(parsed["confidence"])
        if not isinstance(suggested_fix, str) or not suggested_fix.strip():
            raise ValueError("suggested_fix must be a non-empty string")
        if not 0.0 <= model_confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        suggested_fix, remediation_guarded = constrain_dns_remediation(
            suggested_fix.strip(), raw_log
        )
        state["suggested_fix"] = suggested_fix
        certainty = parsed.get("certainty", "Inconclusive")
        if certainty not in CERTAINTY_LEVELS:
            certainty = "Inconclusive"
        state["fix_confidence"] = round(model_confidence, 2)
        state["fix_confidence_reason"] = clean_model_text(
            parsed.get("confidence_reason")
            or "The model did not provide a confidence rationale; review the supporting evidence before acting."
        )
        state["fix_certainty"] = certainty
        state["fix_evidence"] = [clean_model_text(x) for x in (parsed.get("supporting_evidence", []) if isinstance(parsed.get("supporting_evidence", []), list) else [])]
        state["fix_missing_evidence"] = [clean_model_text(x) for x in (parsed.get("missing_evidence", []) if isinstance(parsed.get("missing_evidence", []), list) else [])]
        if remediation_guarded:
            state["fix_confidence"] = min(state["fix_confidence"], 0.50)
            state["fix_certainty"] = "Inconclusive"
            state["fix_missing_evidence"].append(
                "Resolver health evidence before changing DNS infrastructure"
            )
        state["needs_human_review"] = (
            state["fix_confidence"] < CONFIDENCE_THRESHOLD
            or requires_human_review
        )

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[FIX SUGGESTER AGENT] JSON parse error: {e}")
        state["suggested_fix"] = "A remediation recommendation could not be generated because the LLM response could not be parsed."
        state["fix_confidence"] = 0.0
        state["fix_confidence_reason"] = "No confidence assessment was available because the remediation response was invalid."
        state["fix_certainty"] = "Inconclusive"
        state["fix_evidence"] = []
        state["fix_missing_evidence"] = ["A valid structured remediation response"]
        state["needs_human_review"] = True

    print(f"[FIX SUGGESTER AGENT] Fix: {state['suggested_fix']} (confidence: {state['fix_confidence']}, human review: {state['needs_human_review']})")

    return {k: v for k, v in state.items() if k != "investigation_findings"}
