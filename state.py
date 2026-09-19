"""
Ye file sirf ek kaam karti hai: hamara "State" define karna.
State = ek shared dictionary jo har agent (node) ke beech pass hoti hai.
"""

from typing import TypedDict, Optional, List, Annotated
import operator


class InvestigationFinding(TypedDict):
    """Ek Investigator Agent ka output - ek particular 'angle' ka analysis"""
    angle: str              # jaise "Database", "Memory", "Network"
    finding: str             # us angle se kya pata chala
    confidence: float


class IncidentState(TypedDict):
    raw_log: str

    is_anomaly: Optional[bool]
    anomaly_reason: Optional[str]

    # Orchestrator ye fill karega - kitne aur kaunse angles investigate karne hain
    investigation_angles: Optional[List[str]]

    # Investigators (parallel mein chalte hain) apna apna finding yaha add karenge.
    # 'Annotated[List[...], operator.add]' ka matlab: jab multiple parallel nodes
    # isi field mein likhenge, unke results APPEND honge (list mein jud jaayenge),
    # ek doosre ko overwrite nahi karenge. Ye LangGraph ka "reducer" concept hai.
    investigation_findings: Annotated[List[InvestigationFinding], operator.add]

    # Aggregator ye fill karega - sab findings ka combined summary
    root_cause: Optional[str]
    root_cause_confidence: Optional[float]

    suggested_fix: Optional[str]
    fix_confidence: Optional[float]

    needs_human_review: Optional[bool]

    final_report: Optional[str]