"""
FIX SUGGESTER AGENT
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
    max_tokens=2048,
    reasoning_effort="low",
    api_key=os.getenv("GROQ_API_KEY")
)

CONFIDENCE_THRESHOLD = 0.5


def fix_suggester_agent(state: IncidentState) -> IncidentState:
    print("\n[FIX SUGGESTER AGENT] Fix suggest karne ka soch rahe hain...")

    root_cause_confidence = state["root_cause_confidence"]

    # Broad incidents are never safe to auto-approve solely from an LLM
    # confidence score. Escalate them so an engineer reviews the diagnosis
    # before any remediation is applied.
    angle_count = len(state.get("investigation_angles") or [])
    is_critical_log = "critical" in state.get("raw_log", "").lower()
    requires_human_review = angle_count >= 10 or is_critical_log

    if root_cause_confidence < CONFIDENCE_THRESHOLD:
        print(f"[FIX SUGGESTER AGENT] Confidence bahut low hai ({root_cause_confidence}), human review chahiye")
        state["suggested_fix"] = "Confidence bahut low thi, isliye fix suggest nahi kiya gaya"
        state["fix_confidence"] = 0.0
        state["needs_human_review"] = True
        return {k: v for k, v in state.items() if k != "investigation_findings"}

    root_cause = state["root_cause"]

    prompt = f"""You are a senior DevOps engineer. Based on the following root cause analysis, suggest a specific, actionable fix.

Root cause:
"{root_cause}"

Confidence rubric:
- 0.90-1.00: the remediation directly addresses a well-supported cause and has low operational risk
- 0.75-0.89: actionable recommendation, but validation or missing environment details remain
- 0.50-0.74: useful hypothesis that needs significant engineering review
- below 0.50: do not recommend applying automatically
Do not default to a familiar rounded value such as 0.85 or 0.92. Score the
recommendation's evidence and operational safety using two decimal places.

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "suggested_fix": "a concise, specific, actionable fix (2-3 sentences)",
    "confidence": 0.0 to 1.0
}}"""

    response = invoke_with_retry(llm, prompt)
    raw_output = response.content.strip()

    print(f"[FIX SUGGESTER AGENT] LLM ka raw output: {raw_output}")

    try:
        parsed = json.loads(raw_output)
        state["suggested_fix"] = parsed["suggested_fix"]
        state["fix_confidence"] = float(parsed["confidence"])
        state["needs_human_review"] = (
            state["fix_confidence"] < CONFIDENCE_THRESHOLD
            or requires_human_review
        )

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[FIX SUGGESTER AGENT] JSON parse error: {e}")
        state["suggested_fix"] = "Fix suggest nahi ho paya - LLM output parse fail hua"
        state["fix_confidence"] = 0.0
        state["needs_human_review"] = True

    print(f"[FIX SUGGESTER AGENT] Fix: {state['suggested_fix']} (confidence: {state['fix_confidence']}, human review: {state['needs_human_review']})")

    return {k: v for k, v in state.items() if k != "investigation_findings"}
