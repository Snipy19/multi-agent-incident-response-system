from typing import TypedDict, Optional


class IncidentState(TypedDict):
    raw_log: str

    is_anomaly: Optional[bool]
    anomaly_reason: Optional[str]

    root_cause: Optional[str]
    root_cause_confidence: Optional[float]

    suggested_fix: Optional[str]
    fix_confidence: Optional[float]

    needs_human_review: Optional[bool]

    final_report: Optional[str]