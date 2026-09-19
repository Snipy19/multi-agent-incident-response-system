"""
INVESTIGATOR AGENT (RAG-integrated)
--------------------------------------
Kaam: EK specific angle (jaise "Database" ya "Memory") ko deeply investigate
karna, RAG se similar purane real-world patterns ka context lena, aur
finding wapas dena.

IMPORTANT: Ye ek hi function hai jo Orchestrator ke decide kiye har angle
ke liye ALAG SE, PARALLEL mein chalega.
"""

import os
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from state import IncidentState, InvestigationFinding
from vectorstore.retriever import retrieve_similar_patterns
from utils.llm_helper import invoke_with_retry
load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY")
)


def investigator_agent(state: dict) -> dict:
    angle = state["angle"]
    raw_log = state["raw_log"]

    print(f"\n[INVESTIGATOR - {angle}] Investigation shuru...")

    # RAG: similar purane patterns dhoondo real-world knowledge base se
        # Query ko angle-specific banate hain, taaki har investigator ko
    # apne specific angle ke relevant patterns milein, sabko same generic context nahi
    angle_specific_query = f"{angle}: {raw_log}"
    similar_patterns = retrieve_similar_patterns(angle_specific_query, top_k=3)
    context_text = "\n".join(
        [f"- [{p['dataset']}/{p['level']}] {p['template']}" for p in similar_patterns]
    )

    print(f"[INVESTIGATOR - {angle}] RAG context mila:\n{context_text}")

    prompt = f"""You are a DevOps specialist focused specifically on the "{angle}" aspect of a system.

Log entry:
"{raw_log}"

Here are similar log patterns observed in real production systems in the past (for reference context, not necessarily the same incident):
{context_text}

Analyze this log ONLY from the "{angle}" perspective. Use the reference patterns above if relevant to inform your analysis, but base your finding primarily on the actual log entry. What does this log tell us about potential {angle}-related issues?

Respond ONLY with a valid JSON object in this exact format, nothing else, no markdown:
{{
    "finding": "a concise 1-2 sentence finding from the {angle} perspective",
    "confidence": 0.0 to 1.0
}}"""

    response = invoke_with_retry(llm, prompt)
    raw_output = response.content.strip()

    print(f"[INVESTIGATOR - {angle}] LLM ka raw output: {raw_output}")

    try:
        parsed = json.loads(raw_output)
        finding: InvestigationFinding = {
            "angle": angle,
            "finding": parsed["finding"],
            "confidence": float(parsed["confidence"])
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[INVESTIGATOR - {angle}] JSON parse error: {e}")
        finding: InvestigationFinding = {
            "angle": angle,
            "finding": f"{angle} analysis fail hua - parse error",
            "confidence": 0.0
        }

    print(f"[INVESTIGATOR - {angle}] Finding: {finding['finding']} (confidence: {finding['confidence']})")

    return {"investigation_findings": [finding]}