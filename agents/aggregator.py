"""
AGGREGATOR AGENT
-------------------
Kaam: Saare Investigators ke findings ko ek combined root cause mein summarize karna.
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


def aggregator_agent(state: IncidentState) -> IncidentState:
    print("\n[AGGREGATOR AGENT] Sab findings combine kar rahe hain...")

    findings = state["investigation_findings"]

    findings_text = "\n".join(
        [f"- [{f['angle']}] {f['finding']} (confidence: {f['confidence']})" for f in findings]
    )

    print(f"[AGGREGATOR AGENT] Total {len(findings)} findings mile:\n{findings_text}")

    prompt = f"""You are a senior DevOps engineer synthesizing an incident investigation.

Multiple specialists investigated this incident from different angles. Here are their findings:

{findings_text}

Synthesize these findings into ONE unified root cause explanation. Identify
which finding(s) are most likely the PRIMARY cause versus contributing/secondary factors.

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "root_cause": "a clear 2-3 sentence unified root cause, mentioning primary vs secondary factors if relevant",
    "confidence": 0.0 to 1.0
}}"""

    response = invoke_with_retry(llm, prompt)
    raw_output = response.content.strip()

    print(f"[AGGREGATOR AGENT] LLM ka raw output: {raw_output}")

    try:
        parsed = json.loads(raw_output)
        state["root_cause"] = parsed["root_cause"]
        state["root_cause_confidence"] = float(parsed["confidence"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[AGGREGATOR AGENT] JSON parse error: {e}")
        state["root_cause"] = "Aggregation fail hua"
        state["root_cause_confidence"] = 0.0

    print(f"[AGGREGATOR AGENT] Final root cause: {state['root_cause']} (confidence: {state['root_cause_confidence']})")

    return {k: v for k, v in state.items() if k != "investigation_findings"}