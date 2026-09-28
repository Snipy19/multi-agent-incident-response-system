"""
DOCUMENTATION WRITER AGENT
-----------------------------
Kaam: Pura incident (kya hua, kyun hua, kaise fix hua) ek clean,
professional post-mortem report mein likhna.

Report ab disk pe .txt file mein save nahi hota - final_report state
mein jaata hai aur main.py usko database mein store karta hai.
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

Keep it concise but professional, as if it will be read by an engineering team."""

    response = invoke_with_retry(llm, prompt)
    state["final_report"] = response.content.strip()

    print("[DOCUMENTATION WRITER AGENT] Report ready (database mein save hoga)")

    return {k: v for k, v in state.items() if k != "investigation_findings"}