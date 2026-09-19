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
    if state["is_anomaly"]:
        print("[ROUTER] Anomaly mili, Orchestrator ki taraf ja rahe hain")
        return "continue"
    else:
        print("[ROUTER] Anomaly nahi mili, seedha khatam kar rahe hain")
        return "stop"


def spawn_investigators(state: IncidentState):
    """
    YE HAI DYNAMIC SPAWNING WALA CORE FUNCTION.

    Orchestrator ne 'investigation_angles' mein ek list decide ki thi
    (jaise ["Database", "Memory", "Disk I/O"] - lambai dynamic hai).

    Ye function har angle ke liye ek Send() object banata hai.
    Send("investigator", {...}) ka matlab: "investigator node ko
    isi chhote dictionary ke saath ek baar chalao".

    Agar list mein 1 angle hai -> 1 Send -> investigator 1 baar chalega
    Agar list mein 20 angles hain -> 20 Sends -> investigator 20 baar
    parallel chalega. YEHI HAI TERA "DYNAMIC AGENTS" WALA FEATURE.
    """
    angles = state["investigation_angles"]
    print(f"[SPAWNER] {len(angles)} Investigator(s) spawn kar rahe hain: {angles}")

    return [
        Send("investigator", {"angle": angle, "raw_log": state["raw_log"]})
        for angle in angles
    ]


graph = StateGraph(IncidentState)

graph.add_node("log_monitor", log_monitor_agent)
graph.add_node("orchestrator", orchestrator_agent)
graph.add_node("investigator", investigator_agent)
graph.add_node("aggregator", aggregator_agent)
graph.add_node("fix_suggester", fix_suggester_agent)
graph.add_node("report_writer", report_writer_agent)

graph.set_entry_point("log_monitor")

# Log Monitor ke baad: anomaly hai toh Orchestrator, nahi toh END
graph.add_conditional_edges(
    "log_monitor",
    route_after_log_monitor,
    {
        "continue": "orchestrator",
        "stop": END
    }
)

# Orchestrator ke baad: spawn_investigators function decide karta hai
# KITNE Investigator nodes parallel chalenge - ye bhi conditional edge hai,
# but normal wale se alag hai kyunki ye ek FIXED node naam nahi, balki
# Send() objects ki LIST return karta hai
graph.add_conditional_edges(
    "orchestrator",
    spawn_investigators,
    ["investigator"]  # bata rahe hain ki spawn sirf "investigator" node ke liye hoga
)

# Saare parallel Investigators khatam hone ke baad (LangGraph khud wait
# karta hai sabke complete hone tak), Aggregator chalega
graph.add_edge("investigator", "aggregator")

graph.add_edge("aggregator", "fix_suggester")
graph.add_edge("fix_suggester", "report_writer")
graph.add_edge("report_writer", END)

app = graph.compile()