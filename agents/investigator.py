"""
INVESTIGATOR AGENT (RAG-integrated)
"""

import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState, InvestigationFinding
from vectorstore.retriever import retrieve_similar_patterns
from utils.llm_helper import invoke_with_retry
from utils.guardrails import parse_investigator_output

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=2048,
    reasoning_effort="low",
    api_key=os.getenv("GROQ_API_KEY")
)


def investigator_agent(state: dict) -> dict:
    # Each parallel investigator receives one angle and a focused evidence
    # slice. This prevents a large incident log from being duplicated in every
    # prompt and makes high fan-out analysis more token-efficient.
    angle = state["angle"]
    raw_log = state["raw_log"]
    focus_log = state.get("focus_log") or raw_log[:8000]

    print(f"\n[INVESTIGATOR - {angle}] Starting investigation...")

    angle_specific_query = f"{angle}: {focus_log}"
    # RAG provides historical context without replacing evidence from the
    # current incident.
    similar_patterns = retrieve_similar_patterns(angle_specific_query, top_k=3)
    context_text = "\n".join(
        [
            f"- [{p['dataset']}/{p['level']}/{p.get('label', 'Unknown')}] "
            f"{p['template']} | component={p['component']} | "
            f"examples={p.get('example_count', 1)} | sample={p.get('sample_content', '')}"
            for p in similar_patterns
        ]
    )

    print(
        f"[INVESTIGATOR - {angle}] Retrieved {len(similar_patterns)} "
        "RAG context record(s)"
    )

    prompt = f"""You are a DevOps specialist focused specifically on the "{angle}" aspect of a system.

Relevant evidence for this angle:
"{focus_log}"

Here are similar log patterns observed in real production systems in the past (for reference context, not necessarily the same incident):
{context_text}

Analyze this log ONLY from the "{angle}" perspective. Use the reference patterns above if relevant to inform your analysis, but base your finding primarily on the actual log entry. What does this log tell us about potential {angle}-related issues?

Do not treat a numeric confidence value as a calibrated probability. Use it only
as a rough model estimate and explain the real uncertainty with the fields below.
Use "Confirmed" only when the log directly proves the finding; use "Strong
hypothesis" when the evidence is persuasive but a live check is missing; use
"Inconclusive" when competing explanations remain.

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "finding": "a concise 1-2 sentence finding from the {angle} perspective",
    "confidence": 0.0 to 1.0,
    "confidence_reason": "one sentence explaining how direct, complete, and independent the evidence is",
    "certainty": "Confirmed | Strong hypothesis | Inconclusive",
    "supporting_evidence": ["specific facts copied or paraphrased from the log"],
    "missing_evidence": ["the most important check still needed"],
    "alternatives": ["a plausible competing explanation"]
}}"""

    response = invoke_with_retry(
        llm,
        prompt,
        telemetry_id=state.get("telemetry_id"),
    )
    raw_output = response.content.strip()

    print(
        f"[INVESTIGATOR - {angle}] Received LLM response "
        f"({len(raw_output)} characters); validating structured output"
    )

    # Guardrail validation prevents malformed, out-of-range, or unsupported
    # model output from entering the aggregator as if it were verified fact.
    finding: InvestigationFinding = parse_investigator_output(
        raw_output,
        angle,
        focus_log,
    )

    print(
        f"[INVESTIGATOR - {angle}] Finding validated "
        f"(certainty: {finding['certainty']}, confidence: {finding['confidence']})"
    )

    return {"investigation_findings": [finding]}
