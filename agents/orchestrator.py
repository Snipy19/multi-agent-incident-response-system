"""
ORCHESTRATOR AGENT
"""

import os
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState
from utils.llm_helper import invoke_with_retry

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=4096,
    reasoning_effort="low",
    api_key=os.getenv("GROQ_API_KEY")
)


def orchestrator_agent(state: IncidentState) -> IncidentState:
    print("\n[ORCHESTRATOR AGENT] Investigation angles decide kar rahe hain...")

    raw_log = state["raw_log"]
    anomaly_reason = state["anomaly_reason"]

    prompt = f"""You are a senior DevOps engineer planning an incident investigation.

Log entry:
"{raw_log}"

Anomaly reason:
"{anomaly_reason}"

Identify EVERY distinct technical angle/aspect that needs to be investigated
to fully understand this incident. This log may describe a SIMPLE single-issue
problem (1 angle) or a COMPLEX multi-system outage (10, 20, or more angles).

CRITICAL RULE: Scan the log for every named service, system, or component
mentioned (e.g. specific microservices, databases, message queues, cloud
resources, Kubernetes, third-party vendors, security systems). EVERY named
system with a reported problem MUST get its own angle - do not skip any of
them, even if they seem minor. Only merge symptoms together when they belong
to the SAME underlying system (e.g. CPU + memory + disk on the SAME host can
be one "Resource Exhaustion" angle) - never merge across different named
services or vendors.

Keep each angle name SHORT (1-3 words, e.g. "Database", "TLS Certificates", "Kafka Lag").

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "angles": ["angle1", "angle2", ...]
}}"""

    angles = None

    try:
        response = invoke_with_retry(llm, prompt)
        raw_output = response.content.strip()
        print(f"[ORCHESTRATOR AGENT] LLM ka raw output: {raw_output}")
        parsed = json.loads(raw_output)
        angles = parsed["angles"]
    except (json.JSONDecodeError, KeyError, AttributeError) as e:
        print(f"[ORCHESTRATOR AGENT] Pehla attempt fail hua: {e}. Simpler prompt se retry kar rahe hain...")

        fallback_prompt = f"""List every named service, system, or component in this incident log that has a reported problem, as a JSON array of short labels (1-3 words each). Do not skip any named system.

Log (first 1200 characters):
"{raw_log[:1200]}"

Respond ONLY with JSON: {{"angles": ["label1", "label2", ...]}}"""

        try:
            response = invoke_with_retry(llm, fallback_prompt)
            raw_output = response.content.strip()
            print(f"[ORCHESTRATOR AGENT] Fallback raw output: {raw_output}")
            parsed = json.loads(raw_output)
            angles = parsed["angles"]
        except (json.JSONDecodeError, KeyError, AttributeError) as e2:
            print(f"[ORCHESTRATOR AGENT] Fallback bhi fail hua: {e2}")
            angles = None

    if not angles:
        angles = ["General"]

    state["investigation_angles"] = angles
    print(f"[ORCHESTRATOR AGENT] Decided angles: {state['investigation_angles']} (total: {len(state['investigation_angles'])})")

    return state