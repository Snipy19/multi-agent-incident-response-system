"""
LANGGRAPH WORKFLOW
------------------
The workflow follows this sequence:
1. Detect whether the submitted log describes an anomaly.
2. Route anomalies to the orchestrator for grounded investigation planning.
3. Fan out one investigator per selected angle.
4. Aggregate findings, recommend a fix, and write the final report.
"""

from langgraph.graph import StateGraph, END
from langgraph.types import Send
from state import IncidentState
from agents.log_monitor import log_monitor_agent
from agents.orchestrator import orchestrator_agent
from agents.investigator import investigator_agent
from agents.aggregator import aggregator_agent
from agents.fix_suggester import fix_suggester_agent
from agents.report_writer import report_writer_agent


def route_after_log_monitor(state: IncidentState) -> str:
    # This conditional edge prevents normal logs from triggering expensive
    # orchestration and investigation calls.
    if state["is_anomaly"]:
        print("[ROUTER] Anomaly detected; routing to the orchestrator")
        return "continue"
    else:
        print("[ROUTER] No anomaly detected; ending the workflow")
        return "stop"


def spawn_investigators(state: IncidentState):
    """
    Core function for dynamic investigator spawning.

    The orchestrator selects a dynamic list of investigation angles
    (for example, ["Database", "Memory", "Disk I/O"]).

    This function creates one Send() object for each angle.
    Send("investigator", {...}) runs the investigator node once
    with the supplied input dictionary.

    One angle creates one investigator execution; 20 angles create
    20 investigator executions that can run in parallel.
    """
    # LangGraph's Send API creates one independent execution per angle.
    angles = state["investigation_angles"]
    print(f"[SPAWNER] Spawning {len(angles)} investigator(s): {angles}")

    return [
        Send("investigator", {
            "angle": angle,
            "raw_log": state["raw_log"],
            "agent_mode": state.get("agent_mode", "adaptive"),
        })
        for angle in angles
    ]


# Define the graph schema and register each agent as a workflow node.
graph = StateGraph(IncidentState)

graph.add_node("log_monitor", log_monitor_agent)
graph.add_node("orchestrator", orchestrator_agent)
graph.add_node("investigator", investigator_agent)
graph.add_node("aggregator", aggregator_agent)
graph.add_node("fix_suggester", fix_suggester_agent)
graph.add_node("report_writer", report_writer_agent)

# Every analysis starts with anomaly detection.
graph.set_entry_point("log_monitor")

# After the log monitor: continue to the orchestrator or end the workflow.
graph.add_conditional_edges(
    "log_monitor",
    route_after_log_monitor,
    {
        "continue": "orchestrator",
        "stop": END
    }
)

# The orchestrator dynamically decides how many investigator nodes run.
# This conditional edge returns Send objects rather than a fixed node.
graph.add_conditional_edges(
    "orchestrator",
    spawn_investigators,
    ["investigator"]  # Send objects target the investigator node.
)

# LangGraph waits for all parallel investigators before running the aggregator.
graph.add_edge("investigator", "aggregator")

graph.add_edge("aggregator", "fix_suggester")
graph.add_edge("fix_suggester", "report_writer")
graph.add_edge("report_writer", END)

app = graph.compile()
