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
from utils.guardrails import (
    CERTAINTY_LEVELS,
    clean_model_text,
    constrain_cross_service_causality,
    parse_json_object,
)

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
    raw_log = state.get("analysis_log") or state["raw_log"]

    findings_text = "\n".join(
        [f"- [{f['angle']}] {f['finding']} (confidence: {f['confidence']})" for f in findings]
    )

    print(f"[AGGREGATOR AGENT] Received {len(findings)} findings:\n{findings_text}")

    similar_patterns = retrieve_similar_patterns(raw_log, top_k=3)
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

Original submitted log (the primary evidence; do not add facts that are not present here):
{raw_log}

Similar patterns observed in real production systems in the past (for reference context):
{rag_context}

Synthesize these findings into ONE unified root cause explanation. Identify
which finding(s) are most likely the PRIMARY cause versus contributing/secondary factors.

Evidence discipline:
- Treat statements in the original log as observed facts.
- Treat investigator explanations as hypotheses that still require validation.
- Do not connect two services merely because their symptoms occurred together.
- Do not infer that a DNS failure affected Kafka, Redis, networking, or another
  component unless the log or investigator evidence directly connects them.
- If the evidence does not distinguish between competing causes, say so and
  choose "Inconclusive" rather than forcing a primary cause.
- Every causal sentence must be supported by at least one listed evidence item.

Do not present a numeric score as a calibrated probability. Select one certainty
level exactly: Confirmed, Strong hypothesis, or Inconclusive. Confirmed requires
the submitted log to state the fact itself, not merely to infer causality. Use
Strong hypothesis for causal explanations unless the log directly proves the
causal link. Include plausible alternatives instead of hiding uncertainty.

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "root_cause": "a clear 2-3 sentence unified root cause, mentioning primary vs secondary factors if relevant",
    "confidence": 0.0 to 1.0,
    "confidence_reason": "one sentence explaining how direct and complete the evidence is and why uncertainty remains",
    "certainty": "Confirmed | Strong hypothesis | Inconclusive",
    "supporting_evidence": ["specific evidence from the log or investigator findings"],
    "missing_evidence": ["the most important validation still required"],
    "alternatives": ["a plausible competing explanation"]
}}"""

    response = invoke_with_retry(llm, prompt)
    raw_output = response.content.strip()

    print(f"[AGGREGATOR AGENT] LLM ka raw output: {raw_output}")

    try:
        parsed = parse_json_object(raw_output)
        root_cause = clean_model_text(parsed["root_cause"])
        model_confidence = float(parsed["confidence"])
        if not isinstance(root_cause, str) or not root_cause.strip():
            raise ValueError("root_cause must be a non-empty string")
        if not 0.0 <= model_confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        root_cause, causality_guarded = constrain_cross_service_causality(
            root_cause.strip(), raw_log
        )
        state["root_cause"] = root_cause
        certainty = parsed.get("certainty", "Inconclusive")
        if certainty not in CERTAINTY_LEVELS:
            certainty = "Inconclusive"
        state["root_cause_confidence"] = round(model_confidence, 2)
        state["root_cause_confidence_reason"] = clean_model_text(
            parsed.get("confidence_reason")
            or "The model did not provide a confidence rationale; review the evidence and missing validation."
        )
        state["root_cause_certainty"] = certainty
        state["root_cause_evidence"] = [clean_model_text(x) for x in (parsed.get("supporting_evidence", []) if isinstance(parsed.get("supporting_evidence", []), list) else [])]
        state["root_cause_missing_evidence"] = [clean_model_text(x) for x in (parsed.get("missing_evidence", []) if isinstance(parsed.get("missing_evidence", []), list) else [])]
        state["root_cause_alternatives"] = [clean_model_text(x) for x in (parsed.get("alternatives", []) if isinstance(parsed.get("alternatives", []), list) else [])]
        if causality_guarded:
            state["root_cause_confidence"] = min(state["root_cause_confidence"], 0.65)
            state["root_cause_certainty"] = "Strong hypothesis"
            state["root_cause_missing_evidence"].append(
                "Direct correlation showing that the DNS failures affected Redis or Kafka"
            )
            state["root_cause_alternatives"].append(
                "A separate network, broker, cache, or consumer-capacity issue affecting those services"
            )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[AGGREGATOR AGENT] JSON parse error: {e}")
        state["root_cause"] = "Root-cause aggregation failed because the LLM response could not be parsed."
        state["root_cause_confidence"] = 0.0
        state["root_cause_confidence_reason"] = "No confidence assessment was available because the aggregator response was invalid."
        state["root_cause_certainty"] = "Inconclusive"
        state["root_cause_evidence"] = []
        state["root_cause_missing_evidence"] = ["A valid aggregator response"]
        state["root_cause_alternatives"] = []

    print(f"[AGGREGATOR AGENT] Final root cause: {state['root_cause']} (confidence: {state['root_cause_confidence']})")

    return {k: v for k, v in state.items() if k != "investigation_findings"}
