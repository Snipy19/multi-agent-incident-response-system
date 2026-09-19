"""
INVESTIGATOR AGENT
---------------------
Kaam: EK specific angle (jaise "Database" ya "Memory") ko deeply investigate
karna aur uska finding wapas dena.
"""

import os
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState, InvestigationFinding

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY")
)


def investigator_agent(state: dict) -> dict:
    angle = state["angle"]
    raw_log = state["raw_log"]

    print(f"\n[INVESTIGATOR - {angle}] Investigation shuru...")

    prompt = f"""You are a DevOps specialist focused specifically on the "{angle}" aspect of a system.

Log entry:
"{raw_log}"

Analyze this log ONLY from the "{angle}" perspective. What does this log tell us
about potential {angle}-related issues?

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "finding": "a concise 1-2 sentence finding from the {angle} perspective",
    "confidence": 0.0 to 1.0
}}"""

    response = llm.invoke(prompt)
    raw_output = response.content.strip()

    print(f"[INVESTIGATOR - {angle}] LLM ka raw output: {raw_output}")

    try:
        parsed = json.loads(raw_output)
        finding: InvestigationFinding = {
            "angle": angle,
            "finding": parsed["finding"],
            "confidence": float(parsed["confidence"])
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[INVESTIGATOR - {angle}] JSON parse error: {e}")
        finding: InvestigationFinding = {
            "angle": angle,
            "finding": f"{angle} analysis fail hua - parse error",
            "confidence": 0.0
        }

    print(f"[INVESTIGATOR - {angle}] Finding: {finding['finding']} (confidence: {finding['confidence']})")

    return {"investigation_findings": [finding]}