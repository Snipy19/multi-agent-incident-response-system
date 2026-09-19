"""
FIX SUGGESTER AGENT
----------------------
Kaam: root_cause dekh kar ek concrete fix suggest karna.

IMPORTANT LOGIC: agar root_cause_confidence bahut low hai (< 0.5),
toh hum LLM se fix maangte hi nahi - seedha flag laga dete hain
"needs_human_review = True". Ye real-world mein important hai:
agar diagnosis khud uncertain hai, blindly fix suggest karna
production mein galat action le sakta hai.
"""

import os
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY")
)

CONFIDENCE_THRESHOLD = 0.5


def fix_suggester_agent(state: IncidentState) -> IncidentState:
    print("\n[FIX SUGGESTER AGENT] Fix suggest karne ka soch rahe hain...")

    root_cause_confidence = state["root_cause_confidence"]

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

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "suggested_fix": "a concise, specific, actionable fix (2-3 sentences)",
    "confidence": 0.0 to 1.0
}}"""

    response = llm.invoke(prompt)
    raw_output = response.content.strip()

    print(f"[FIX SUGGESTER AGENT] LLM ka raw output: {raw_output}")

    try:
        parsed = json.loads(raw_output)
        state["suggested_fix"] = parsed["suggested_fix"]
        state["fix_confidence"] = float(parsed["confidence"])
        state["needs_human_review"] = state["fix_confidence"] < CONFIDENCE_THRESHOLD

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[FIX SUGGESTER AGENT] JSON parse error: {e}")
        state["suggested_fix"] = "Fix suggest nahi ho paya - LLM output parse fail hua"
        state["fix_confidence"] = 0.0
        state["needs_human_review"] = True

    print(f"[FIX SUGGESTER AGENT] Fix: {state['suggested_fix']} (confidence: {state['fix_confidence']}, human review: {state['needs_human_review']})")

    return {k: v for k, v in state.items() if k != "investigation_findings"}