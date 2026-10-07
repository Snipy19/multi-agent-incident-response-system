"""
ORCHESTRATOR AGENT
------------------
Selects grounded technical investigation angles from an incident log.
"""

import json
import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from state import IncidentState
from utils.llm_helper import invoke_with_retry
from utils.agent_planning import (
    MAX_AGENT_COUNT,
    deduplicate_angles,
    requested_load_test_targets,
)

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=4096,
    reasoning_effort="low",
    api_key=os.getenv("GROQ_API_KEY"),
)

def orchestrator_agent(state: IncidentState) -> IncidentState:
    # The orchestrator controls cost and relevance by selecting only angles
    # supported by the submitted evidence.
    print("\n[ORCHESTRATOR AGENT] Selecting investigation angles...")

    raw_log = state["raw_log"]
    anomaly_reason = state["anomaly_reason"]

    if state.get("agent_mode") == "load_test":
        requested_count = min(
            int(state.get("requested_agent_count") or 1),
            MAX_AGENT_COUNT,
        )
        angles = requested_load_test_targets(raw_log, requested_count)
        state["investigation_angles"] = angles
        print(f"[ORCHESTRATOR AGENT] Load-test mode selected {len(angles)} targets")
        return state

    prompt = f"""You are a senior DevOps engineer planning an incident investigation.

Log entry:
"{raw_log}"

Anomaly reason:
"{anomaly_reason}"

Identify the technical angles/aspects that need to be investigated to
understand this incident.

STRICT GROUNDING RULE - this is critical:
- Create an angle only for a system, component, or symptom explicitly
  mentioned in the log, or directly implied by named evidence.
- Do not invent speculative systems that are not supported by the log.
- Do not create one angle for every service, log line, or repeated symptom.
- Group services that show the same failure pattern under one investigation.
- Create separate angles only for independent failure domains or competing
  root-cause hypotheses that require different evidence.
- For short logs, produce only 1-3 focused angles.
- For complex logs, produce more angles only when they represent distinct
  failure domains; complexity alone does not justify one agent per service.
- When uncertain, choose fewer high-relevance angles rather than speculation.

Keep each angle name short (1-3 words, for example: "Database", "TLS Certificates", "Kafka Lag").

Respond ONLY with a valid JSON object in this exact format, with no markdown:
{{
    "angles": ["angle1", "angle2", ...]
}}"""

    angles = None

    # The fallback prompt is intentionally shorter and more constrained so a
    # transient formatting failure does not stop the entire incident run.
    try:
        response = invoke_with_retry(llm, prompt)
        raw_output = response.content.strip()
        print(f"[ORCHESTRATOR AGENT] Raw LLM output: {raw_output}")
        parsed = json.loads(raw_output)
        angles = parsed["angles"]
    except (json.JSONDecodeError, KeyError, AttributeError) as error:
        print(f"[ORCHESTRATOR AGENT] First attempt failed: {error}. Retrying with a simpler prompt...")

        fallback_prompt = f"""List only the systems/components explicitly named in this incident log
that have a reported problem. Return a JSON array of short labels. Do not add
anything that is not literally supported by the log.

Log (first 1200 characters):
"{raw_log[:1200]}"

Respond ONLY with JSON: {{"angles": ["label1", "label2", ...]}}"""

        try:
            response = invoke_with_retry(llm, fallback_prompt)
            raw_output = response.content.strip()
            print(f"[ORCHESTRATOR AGENT] Fallback raw output: {raw_output}")
            parsed = json.loads(raw_output)
            angles = parsed["angles"]
        except (json.JSONDecodeError, KeyError, AttributeError) as fallback_error:
            print(f"[ORCHESTRATOR AGENT] Fallback attempt also failed: {fallback_error}")
            angles = None

    if not angles:
        angles = ["General"]

    if not isinstance(angles, list):
        angles = ["General"]
    angles = deduplicate_angles(angles)

    state["investigation_angles"] = angles
    print(f"[ORCHESTRATOR AGENT] Selected angles: {angles} (total: {len(angles)})")
    return state
