"""Investigation subgraph — runs all specialist analysts in parallel.

This is compiled as a standalone subgraph and plugged into the supervisor
graph as a single node.  Subgraph pattern:
  - Keeps each agent independently testable.
  - Parallel fan-out via Send (map-reduce) for concurrent specialist runs.
  - State reducers (_merge_findings) safely merge concurrent writes.
"""

from langgraph.graph import END, START, StateGraph

from incident_commander.agents.change_analyst import change_analyst_node
from incident_commander.agents.log_analyst import log_analyst_node
from incident_commander.agents.metrics_analyst import metrics_analyst_node
from incident_commander.agents.runbook_retriever import runbook_retriever_node
from incident_commander.core.state import IncidentStateDict


def build_investigation_subgraph() -> object:
    """Build and compile the investigation subgraph."""
    builder = StateGraph(IncidentStateDict)

    builder.add_node("log_analyst", log_analyst_node)
    builder.add_node("metrics_analyst", metrics_analyst_node)
    builder.add_node("change_analyst", change_analyst_node)
    builder.add_node("runbook_retriever", runbook_retriever_node)

    # All four analysts run in parallel from START
    builder.add_edge(START, "log_analyst")
    builder.add_edge(START, "metrics_analyst")
    builder.add_edge(START, "change_analyst")
    builder.add_edge(START, "runbook_retriever")

    # All converge at END — LangGraph waits for all parallel branches
    builder.add_edge("log_analyst", END)
    builder.add_edge("metrics_analyst", END)
    builder.add_edge("change_analyst", END)
    builder.add_edge("runbook_retriever", END)

    return builder.compile()


# Module-level compiled subgraph — reused across requests
investigation_subgraph = build_investigation_subgraph()
