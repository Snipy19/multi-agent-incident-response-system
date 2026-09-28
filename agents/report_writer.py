"""
DOCUMENTATION WRITER AGENT
-----------------------------
Kaam: Incident ka short narrative summary likhna (UI mein "Full Report" mein dikhta hai).

Report disk pe save nahi hota - final_report state mein jaata hai aur
main.py usko database mein store karta hai. Downloadable PDF/MD/TXT
report_export.py se banta hai (real data se).
"""

import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState
from utils.llm_helper import invoke_with_retry

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=2048,
    reasoning_effort="low",
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

STRICT RULES:
- Use ONLY the facts provided above. Do NOT invent incident IDs, dates, times,
  durations, customer impact numbers, team names, or people.
- The fix is a RECOMMENDATION only. Do NOT say it was applied, that the incident
  was resolved, or that any action has already been taken.
- If a detail is not provided, leave it out instead of guessing.
- Do NOT add a "prepared by" line.

Keep it concise but professional, as if it will be read by an engineering team."""

    response = invoke_with_retry(llm, prompt)
    state["final_report"] = response.content.strip()

    print("[DOCUMENTATION WRITER AGENT] Report ready (database mein save hoga)")

    return {k: v for k, v in state.items() if k != "investigation_findings"}