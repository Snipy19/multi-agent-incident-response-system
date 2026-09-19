"""
ORCHESTRATOR AGENT
---------------------
Kaam: Log dekh kar decide karna ki iss incident ko investigate karne ke
liye kitne aur kaunse "angles" (aspects) chahiye.

Jaise: agar log sirf database timeout bolta hai -> sirf 1 angle (Database)
Agar log complex multi-system outage hai -> 10, 20, ya zyada angles

Ye list DYNAMIC hai - LLM khud decide karta hai kitni lambi honi chahiye.
Agar pehla attempt fail ho jaaye (bahut lambe/complex logs ke saath LLM
kabhi kabhi khali response deta hai), toh ek chhota fallback prompt se
retry karte hain, taaki system crash na ho aur "General" pe fall back
karna bhi rare case ban jaaye.
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
    max_tokens=1024,
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
Be thorough - if the log mentions many separate systems, symptoms, or components,
list a SEPARATE angle for each one. Do not merge distinct issues into one angle.
Keep each angle name SHORT (1-3 words, e.g. "Database", "TLS Certificates", "Kafka Lag").

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "angles": ["angle1", "angle2", ...]
}}"""

    angles = None

    # Pehla attempt - normal prompt
    try:
        response = invoke_with_retry(llm, prompt)
        raw_output = response.content.strip()
        print(f"[ORCHESTRATOR AGENT] LLM ka raw output: {raw_output}")
        parsed = json.loads(raw_output)
        angles = parsed["angles"]
    except (json.JSONDecodeError, KeyError, AttributeError) as e:
        print(f"[ORCHESTRATOR AGENT] Pehla attempt fail hua: {e}. Simpler prompt se retry kar rahe hain...")

        # Doosra attempt - chhota, simpler prompt (agar bada log confuse kar raha tha)
        fallback_prompt = f"""List the main technical problem categories mentioned in this incident log, as a JSON array of short labels (1-3 words each).

Log (first 800 characters):
"{raw_log[:800]}"

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