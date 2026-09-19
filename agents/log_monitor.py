"""
LOG MONITOR AGENT (Real LLM version)
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


def log_monitor_agent(state: IncidentState) -> IncidentState:
    print("\n[LOG MONITOR AGENT] LLM ko log bhej rahe hain...")

    raw_log = state["raw_log"]

    prompt = f"""You are a DevOps log analysis expert. Analyze the following log entry and determine if it represents an anomaly (a real problem) or normal system behavior.

Log entry:
"{raw_log}"

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown, no explanation outside the JSON:
{{
    "is_anomaly": true or false,
    "reason": "a short one-sentence explanation of your judgment"
}}"""

    response = invoke_with_retry(llm, prompt)
    raw_output = response.content.strip()

    print(f"[LOG MONITOR AGENT] LLM ka raw output: {raw_output}")

    try:
        parsed = json.loads(raw_output)
        state["is_anomaly"] = parsed["is_anomaly"]
        state["anomaly_reason"] = parsed["reason"]
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[LOG MONITOR AGENT] JSON parse karne mein error: {e}")
        state["is_anomaly"] = True
        state["anomaly_reason"] = "LLM output parse nahi ho paya, safety ke liye anomaly maan liya"

    print(f"[LOG MONITOR AGENT] Final decision -> is_anomaly: {state['is_anomaly']}, reason: {state['anomaly_reason']}")

    return state