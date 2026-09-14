"""
DOCUMENTATION WRITER AGENT
------------------------------
Kaam: Pura incident (kya hua, kyun hua, kaise fix hua) ek clean,
professional report mein likhna - jaise real companies mein
"post-mortem" document banta hai.

Ye report ek .txt file mein bhi save hota hai reports/ folder mein.
"""

import os
import json
from datetime import datetime
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY")
)


def report_writer_agent(state: IncidentState) -> IncidentState:
    print("\n[DOCUMENTATION WRITER AGENT] Report likh rahe hain...")

    prompt = f"""You are a technical writer creating an incident post-mortem report for a DevOps team.

Here is all the information about this incident:
- Original log: "{state['raw_log']}"
- Anomaly detected: {state['is_anomaly']}
- Anomaly reason: "{state['anomaly_reason']}"
- Root cause: "{state['root_cause']}"
- Root cause confidence: {state['root_cause_confidence']}
- Suggested fix: "{state['suggested_fix']}"
- Fix confidence: {state['fix_confidence']}
- Needs human review: {state['needs_human_review']}

Write a clean, professional incident report with these sections:
1. Summary
2. Root Cause
3. Recommended Fix
4. Confidence & Review Status

Keep it concise but professional, as if it will be read by an engineering team."""

    response = llm.invoke(prompt)
    report_text = response.content.strip()

    state["final_report"] = report_text

    # Report ko file mein bhi save kar do
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"reports/incident_{timestamp}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[DOCUMENTATION WRITER AGENT] Report ban gaya aur save hua: {filepath}")

    return state