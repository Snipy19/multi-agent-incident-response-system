"""
AGGREGATOR AGENT (RAG-integrated)
"""

import os
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState
from vectorstore.retriever import retrieve_similar_patterns
from utils.llm_helper import invoke_with_retry

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=2048,
    reasoning_effort="low",
    api_key=os.getenv("GROQ_API_KEY")
)


def aggregator_agent(state: IncidentState) -> IncidentState:
    # The aggregator compares specialist findings and separates primary
    # causes from secondary or cascading symptoms.
    print("\n[AGGREGATOR AGENT] Combining investigator findings...")

    findings = state["investigation_findings"]

    findings_text = "\n".join(
        [f"- [{f['angle']}] {f['finding']} (confidence: {f['confidence']})" for f in findings]
    )

    print(f"[AGGREGATOR AGENT] Received {len(findings)} findings:\n{findings_text}")

    similar_patterns = retrieve_similar_patterns(state["raw_log"], top_k=3)
    rag_context = "\n".join(
        [
            f"- [{p['dataset']}/{p['level']}/{p.get('label', 'Unknown')}] "
            f"{p['template']} | component={p['component']} | "
            f"examples={p.get('example_count', 1)} | sample={p.get('sample_content', '')}"
            for p in similar_patterns
        ]
    )

    prompt = f"""You are a senior DevOps engineer synthesizing an incident investigation.

Multiple specialists investigated this incident from different angles. Here are their findings:

{findings_text}

Similar patterns observed in real production systems in the past (for reference context):
{rag_context}

Synthesize these findings into ONE unified root cause explanation. Identify
which finding(s) are most likely the PRIMARY cause versus contributing/secondary factors.

Confidence rubric:
- 0.90-1.00: the primary cause is directly supported by multiple independent findings
- 0.75-0.89: strongly supported, but important confirmation is still missing
- 0.50-0.74: plausible competing explanations remain
- below 0.50: insufficient evidence for a reliable root cause
Do not default to 0.85, 0.90, 0.92, or 0.93. Use two decimal places and reflect
the uncertainty caused by missing metrics, traces, configuration, and live validation.

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
        state["root_cause"] = "Root-cause aggregation failed because the LLM response could not be parsed."
        state["root_cause_confidence"] = 0.0

    print(f"[AGGREGATOR AGENT] Final root cause: {state['root_cause']} (confidence: {state['root_cause_confidence']})")

    return {k: v for k, v in state.items() if k != "investigation_findings"}
