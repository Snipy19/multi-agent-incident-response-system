"""
ORCHESTRATOR AGENT
---------------------
Kaam: Log dekh kar decide karna ki iss incident ko investigate karne ke
liye kitne aur kaunse "angles" (aspects) chahiye.

Jaise: agar log sirf database timeout bolta hai -> sirf 1 angle (Database)
Agar log database + memory + disk teeno mention karta hai -> 3 angles

Ye list DYNAMIC hai - LLM khud decide karta hai kitni lambi honi chahiye.
Isi list ke hisaab se baad mein utne hi Investigator Agents spawn honge.
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

Identify the distinct technical angles/aspects that need to be investigated
to fully understand this incident. Examples of angles: "Database", "Network",
"Memory", "Disk I/O", "Authentication", "Application Logic", "External API",
"Configuration".

Only include angles that are actually relevant based on the log content.
A simple log might need just 1 angle. A complex log mentioning multiple
symptoms might need 3-5 angles. Do not invent irrelevant angles.

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "angles": ["angle1", "angle2", ...]
}}"""

    response = invoke_with_retry(llm, prompt)
    raw_output = response.content.strip()

    print(f"[ORCHESTRATOR AGENT] LLM ka raw output: {raw_output}")

    try:
        parsed = json.loads(raw_output)
        angles = parsed["angles"]
        if not angles:  # agar khali list aa gayi, safety fallback
            angles = ["General"]
        state["investigation_angles"] = angles
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[ORCHESTRATOR AGENT] JSON parse error: {e}")
        state["investigation_angles"] = ["General"]  # fallback: 1 generic angle

    print(f"[ORCHESTRATOR AGENT] Decided angles: {state['investigation_angles']} (total: {len(state['investigation_angles'])})")

    return state