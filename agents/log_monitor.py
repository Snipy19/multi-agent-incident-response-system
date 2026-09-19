"""
LOG MONITOR AGENT (Real LLM version)
--------------------------------------
Kaam: raw_log ko ek real LLM (Groq) ko bhejna aur usse decide karwana
ki ye log ek "anomaly" (problem) hai ya normal activity hai.

Koi keyword-matching wala fake logic nahi - LLM khud judge karega
log ko padh kar, jaise ek real DevOps engineer karta.
"""

import os
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState
from utils.llm_helper import invoke_with_retry

load_dotenv()


llm = ChatGroq(
        model="openai/gpt-oss-20b",   # Groq's current fast free-tier model  
    temperature=0,                    # 0 matlab consistent/deterministic output, kam randomness
    api_key=os.getenv("GROQ_API_KEY")
)


def log_monitor_agent(state: IncidentState) -> IncidentState:
    print("\n[LOG MONITOR AGENT] LLM ko log bhej rahe hain...")

    raw_log = state["raw_log"]

    # Ye prompt hai jo hum LLM ko denge - isme clearly bata rahe hain
    # kya karna hai aur kis format mein jawab chahiye
    prompt = f"""You are a DevOps log analysis expert. Analyze the following log entry and determine if it represents an anomaly (a real problem) or normal system behavior.

Log entry:
"{raw_log}"

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown, no explanation outside the JSON:
{{
    "is_anomaly": true or false,
    "reason": "a short one-sentence explanation of your judgment"
}}"""

    # LLM ko call karo
    response = invoke_with_retry(llm, prompt)
    raw_output = response.content.strip()

    print(f"[LOG MONITOR AGENT] LLM ka raw output: {raw_output}")

    # LLM ka output JSON string hota hai, usko Python dictionary mein convert karo
    try:
        parsed = json.loads(raw_output)
        state["is_anomaly"] = parsed["is_anomaly"]
        state["anomaly_reason"] = parsed["reason"]
    except (json.JSONDecodeError, KeyError) as e:
        # safe fallback
        print(f"[LOG MONITOR AGENT] JSON parse karne mein error: {e}")
        state["is_anomaly"] = True   
        state["anomaly_reason"] = "LLM output parse nahi ho paya, safety ke liye anomaly maan liya"

    print(f"[LOG MONITOR AGENT] Final decision -> is_anomaly: {state['is_anomaly']}, reason: {state['anomaly_reason']}")

    return state