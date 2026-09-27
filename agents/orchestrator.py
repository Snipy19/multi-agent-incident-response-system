"""
ORCHESTRATOR AGENT
---------------------
Kaam: Log dekh kar decide karna ki iss incident ko investigate karne ke
liye kitne aur kaunse "angles" (aspects) chahiye.

GROUNDING RULE: Angles sirf unhi cheezon pe banenge jo log mein explicitly
mention hain ya directly implied hain - koi speculative/hypothetical angle
nahi banega jo log mein hai hi nahi (jaise agar log sirf CPU+latency bolta
hai, toh "Database", "Third-Party Gateway" jaisे angles nahi banenge sirf
isliye ki "shayad involved ho sakte hain").
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

Identify the technical angles/aspects that need to be investigated to
understand this incident.

STRICT GROUNDING RULE - this is critical:
- ONLY create an angle for a system, component, or symptom that is
  EXPLICITLY mentioned in the log text above, OR is a direct, named
  component of something explicitly mentioned (e.g. if the log says
  "payment-service" and it's known to run on Kubernetes, "Kubernetes"
  is acceptable only if the log itself implies infrastructure context -
  otherwise stick to what is literally stated).
- DO NOT invent speculative angles for systems that are NOT mentioned,
  just because they "could theoretically be involved" (e.g. do not add
  "Database", "Third-Party Gateway", "Network", "Load Balancer" unless
  the log actually references them).
- If the log describes only 1-2 symptoms, you should typically produce
  only 1-3 angles. Only produce many angles (10+) when the log itself
  actually names many distinct systems/components with reported problems.
- When in doubt, investigate FEWER angles with higher relevance rather
  than more angles with speculation. A short log deserves a short list.

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

        fallback_prompt = f"""List only the systems/components EXPLICITLY named in this incident log that have a reported problem, as a JSON array of short labels (1-3 words each). Do not add anything not literally mentioned.

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