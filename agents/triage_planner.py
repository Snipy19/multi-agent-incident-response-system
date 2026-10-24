"""
TRIAGE AND INVESTIGATION PLANNER AGENT
--------------------------------------
Combines anomaly detection and evidence-grounded investigation planning into
one real structured LLM call. This removes a serial request without changing
the dynamic fan-out behavior.
"""

import json
import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from state import IncidentState
from utils.agent_planning import (
    MAX_AGENT_COUNT,
    deduplicate_angles,
    ensure_failure_domain_coverage,
    requested_load_test_targets,
)
from utils.guardrails import clean_model_text, parse_json_object
from utils.llm_helper import LLM_TIMEOUT_SECONDS, invoke_with_retry

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=4096,
    reasoning_effort="low",
    timeout=LLM_TIMEOUT_SECONDS,
    max_retries=0,
    api_key=os.getenv("GROQ_API_KEY"),
)


def triage_planner_agent(state: IncidentState) -> IncidentState:
    """Classify the log and select grounded investigation angles in one call."""
    print("\n[TRIAGE PLANNER AGENT] Detecting anomaly and planning investigation...")

    raw_log = state.get("analysis_log") or state["raw_log"]
    prompt = f"""You are a senior DevOps incident triage planner.

Analyze this submitted log:
\"{raw_log}\"

Return both an anomaly decision and a focused investigation plan.

Evidence and planning rules:
- Treat only statements in the submitted log as observed facts.
- Set is_anomaly=false for normal, successful, or healthy logs.
- Set is_anomaly=true when the log reports errors, failures, abnormal latency,
  capacity exhaustion, restarts, timeouts, or other operational impact.
- For an anomalous log, create angles only for explicit components, symptoms,
  or independent failure domains supported by the log.
- Group related symptoms; do not create one angle per line, metric, or repeated
  error. Do not invent systems that are not supported by the log.
- Prefer fewer focused angles. Each angle should represent a distinct evidence
  question that a specialist can investigate.

Respond ONLY with valid JSON in this exact format:
{{
    \"is_anomaly\": true or false,
    \"reason\": \"one concise sentence grounded in the log\",
    \"angles\": [\"Database\", \"Network\"]
}}"""

    try:
        response = invoke_with_retry(llm, prompt)
        raw_output = response.content.strip()
        print(
            "[TRIAGE PLANNER AGENT] Received LLM response "
            f"({len(raw_output)} characters); validating structured output"
        )
        parsed = parse_json_object(raw_output)

        is_anomaly = parsed["is_anomaly"]
        reason = parsed["reason"]
        angles = parsed.get("angles", [])

        if not isinstance(is_anomaly, bool):
            raise ValueError("is_anomaly must be boolean")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        if not isinstance(angles, list):
            raise ValueError("angles must be a list")

        state["is_anomaly"] = is_anomaly
        state["anomaly_reason"] = clean_model_text(reason).strip()
        state["investigation_angles"] = ensure_failure_domain_coverage(raw_log, angles)
    except (json.JSONDecodeError, KeyError, ValueError, AttributeError) as error:
        print(
            "[TRIAGE PLANNER AGENT] Structured response validation failed: "
            f"{type(error).__name__}"
        )
        # A malformed triage response must not silently skip a possible
        # incident. Adaptive mode falls back to one bounded investigation.
        state["is_anomaly"] = True
        state["anomaly_reason"] = (
            "The triage response could not be parsed; investigation continued for safety."
        )
        state["investigation_angles"] = ["General"]

    # Load-test mode intentionally bypasses adaptive angle selection after the
    # real triage call so its requested execution count remains exact.
    if state.get("agent_mode") == "load_test":
        requested_count = min(
            int(state.get("requested_agent_count") or 1),
            MAX_AGENT_COUNT,
        )
        state["is_anomaly"] = True
        state["investigation_angles"] = requested_load_test_targets(
            raw_log, requested_count
        )
        state["anomaly_reason"] = state.get("anomaly_reason") or (
            "Load-test mode requested a controlled investigator fan-out."
        )
    elif state["is_anomaly"]:
        if not state.get("investigation_angles"):
            state["investigation_angles"] = ["General"]
    else:
        state["investigation_angles"] = []

    print(
        f"[TRIAGE PLANNER AGENT] anomaly={state['is_anomaly']}; "
        f"angles={state['investigation_angles']}"
    )
    return state
