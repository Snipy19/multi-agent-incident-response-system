from langgraph.graph import StateGraph, END
from state import IncidentState
from agents.log_monitor import log_monitor_agent
from agents.root_cause_analyzer import root_cause_analyzer_agent
from agents.fix_suggester import fix_suggester_agent
from agents.report_writer import report_writer_agent


def route_after_log_monitor(state: IncidentState) -> str:
    if state["is_anomaly"]:
        print("[ROUTER] Anomaly mili, Root Cause Analyzer ki taraf ja rahe hain")
        return "continue"
    else:
        print("[ROUTER] Anomaly nahi mili, seedha khatam kar rahe hain")
        return "stop"


graph = StateGraph(IncidentState)

graph.add_node("log_monitor", log_monitor_agent)
graph.add_node("root_cause_analyzer", root_cause_analyzer_agent)
graph.add_node("fix_suggester", fix_suggester_agent)
graph.add_node("report_writer", report_writer_agent)

graph.set_entry_point("log_monitor")

graph.add_conditional_edges(
    "log_monitor",
    route_after_log_monitor,
    {
        "continue": "root_cause_analyzer",
        "stop": END
    }
)

graph.add_edge("root_cause_analyzer", "fix_suggester")
graph.add_edge("fix_suggester", "report_writer")
graph.add_edge("report_writer", END)

app = graph.compile()