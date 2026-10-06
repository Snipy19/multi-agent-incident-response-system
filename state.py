"""
This file defines the shared state passed between workflow nodes.
"""

from typing import TypedDict, Optional, List, Annotated
import operator


class InvestigationFinding(TypedDict):
    """Output from one investigator for a specific technical angle."""
    angle: str              # For example: Database, Memory, or Network.
    finding: str             # Evidence discovered for this angle.
    confidence: float


class IncidentState(TypedDict):
    raw_log: str

    is_anomaly: Optional[bool]
    anomaly_reason: Optional[str]

    # The orchestrator selects the number and names of investigation angles.
    investigation_angles: Optional[List[str]]

    # Parallel investigators append their findings through operator.add.
    # This LangGraph reducer prevents one investigator from overwriting another.
    investigation_findings: Annotated[List[InvestigationFinding], operator.add]

    # The aggregator fills the combined root-cause summary.
    root_cause: Optional[str]
    root_cause_confidence: Optional[float]

    suggested_fix: Optional[str]
    fix_confidence: Optional[float]

    needs_human_review: Optional[bool]

    final_report: Optional[str]
