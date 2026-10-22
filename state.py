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
    confidence_reason: str
    certainty: str
    supporting_evidence: List[str]
    missing_evidence: List[str]
    alternatives: List[str]


class IncidentState(TypedDict):
    raw_log: str

    # Adaptive mode follows evidence; load_test mode intentionally requests a
    # controlled number of real investigator executions for scalability tests.
    agent_mode: Optional[str]
    requested_agent_count: Optional[int]

    is_anomaly: Optional[bool]
    anomaly_reason: Optional[str]

    # Adaptive mode selects independent hypotheses; load-test mode may select
    # an exact requested count for scalability benchmarking.
    investigation_angles: Optional[List[str]]

    # Parallel investigators append their findings through operator.add.
    # This LangGraph reducer prevents one investigator from overwriting another.
    investigation_findings: Annotated[List[InvestigationFinding], operator.add]

    # The aggregator fills the combined root-cause summary.
    root_cause: Optional[str]
    root_cause_confidence: Optional[float]
    root_cause_certainty: Optional[str]
    root_cause_evidence: Optional[List[str]]
    root_cause_missing_evidence: Optional[List[str]]
    root_cause_alternatives: Optional[List[str]]
    root_cause_confidence_reason: Optional[str]

    suggested_fix: Optional[str]
    fix_confidence: Optional[float]
    fix_certainty: Optional[str]
    fix_evidence: Optional[List[str]]
    fix_missing_evidence: Optional[List[str]]
    fix_confidence_reason: Optional[str]

    needs_human_review: Optional[bool]

    final_report: Optional[str]
