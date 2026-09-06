"""
ROOT CAUSE ANALYZER AGENT
---------------------------
Kaam: Agar Log Monitor ne bola "haan ye anomaly hai", toh ye agent
LLM se pucchega "iska asli root cause kya ho sakta hai" aur kitna
confident hai LLM apne jawab pe (0.0 se 1.0 ke beech).

Confidence score important hai kyunki humein baad mein decide karna hai
ki human review chahiye ya nahi - agar LLM khud confident nahi hai,
toh blindly aage fix suggest karna risky hai.
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


def root_cause_analyzer_agent(state: IncidentState) -> IncidentState:
    print("\n[ROOT CAUSE ANALYZER AGENT] Root cause dhoond rahe hain...")

    raw_log = state["raw_log"]
    anomaly_reason = state["anomaly_reason"]

    prompt = f"""You are a senior DevOps engineer investigating a production incident.

Log entry:
"{raw_log}"

Initial anomaly detection reason:
"{anomaly_reason}"

Analyze this log and determine the most likely root cause of this issue.
Also give a confidence score between 0.0 and 1.0 representing how confident
you are in this root cause diagnosis (1.0 = completely certain, 0.5 = uncertain, 0.2 = mostly guessing).

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "root_cause": "a concise 1-2 sentence explanation of the likely root cause",
    "confidence": 0.0 to 1.0
}}"""

    response = llm.invoke(prompt)
    raw_output = response.content.strip()

    print(f"[ROOT CAUSE ANALYZER AGENT] LLM ka raw output: {raw_output}")

    try:
        parsed = json.loads(raw_output)
        state["root_cause"] = parsed["root_cause"]
        state["root_cause_confidence"] = float(parsed["confidence"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[ROOT CAUSE ANALYZER AGENT] JSON parse error: {e}")
        state["root_cause"] = "Root cause determine nahi ho paya - LLM output parse fail hua"
        state["root_cause_confidence"] = 0.0

    print(f"[ROOT CAUSE ANALYZER AGENT] Root cause: {state['root_cause']} (confidence: {state['root_cause_confidence']})")

    return state