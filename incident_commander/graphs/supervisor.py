"""Supervisor graph — the top-level incident orchestration graph.

Architecture:
  supervisor → [investigate (subgraph) | human_approval | executor | resolve | escalate]
  
HITL pattern:
  - interrupt_before=["human_approval"] pauses the graph.
  - The API caller receives the current state (proposed_actions, diagnosis).
  - The engineer calls PATCH /incidents/{id}/approve, which calls
    graph.update_state() to inject approved_action, then reinvokes.
  - The graph resumes from the checkpoint — no work is repeated.

This module exports `graph` at the module level so langgraph.json can
locate it directly: "./incident_commander/graphs/supervisor.py:graph"
"""

from langgraph.graph import END, START, StateGraph

from incident_commander.agents.executor import executor_node
from incident_commander.agents.planner import planner_node
from incident_commander.agents.resolver import escalation_node, resolver_node
from incident_commander.agents.supervisor import (
    route_after_executor,
    route_after_planner,
    route_after_supervisor,
    supervisor_node,
)
from incident_commander.core.state import IncidentStateDict
from incident_commander.graphs.investigation_subgraph import investigation_subgraph
from incident_commander.services.checkpointer import get_sync_checkpointer


def _human_approval_node(state: dict) -> dict:
    """Placeholder node — execution pauses here via interrupt_before.

    The graph serialises its full state to the checkpointer and returns
    control to the API caller.  Nothing runs inside this function during
    normal HITL flow; it only executes if the graph is resumed after
    update_state() has injected the approved_action.
    """
    return {}


def build_graph(checkpointer: object | None = None) -> object:
    """Build and compile the supervisor graph.

    Args:
        checkpointer: Optional checkpointer to wire in.  Pass None for tests
                      that exercise routing without persistence.
    """
    builder = StateGraph(IncidentStateDict)

    # ── Nodes ──────────────────────────────────────────────────────────────
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("investigate", investigation_subgraph)
    builder.add_node("planner", planner_node)
    builder.add_node("human_approval", _human_approval_node)
    builder.add_node("executor", executor_node)
    builder.add_node("resolve", resolver_node)
    builder.add_node("escalate", escalation_node)

    # ── Edges ──────────────────────────────────────────────────────────────
    builder.add_edge(START, "supervisor")

    # Supervisor fans out based on routing_decision
    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "investigate": "investigate",
            "human_approval": "human_approval",
            "execute": "executor",
            "resolve": "resolve",
            "escalate": "escalate",
        },
    )

    # After investigation always plan
    builder.add_edge("investigate", "planner")

    # Planner routes back to supervisor (for another cycle or HITL gate)
    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "supervisor": "supervisor",
            "human_approval": "human_approval",
            "executor": "executor",
        },
    )

    # After human approves, execute
    builder.add_edge("human_approval", "executor")

    # After execution, resolve or escalate
    builder.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "resolve": "resolve",
            "escalate": "escalate",
        },
    )

    builder.add_edge("resolve", END)
    builder.add_edge("escalate", END)

    # ── Compile ────────────────────────────────────────────────────────────
    compile_kwargs: dict = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
        # Pause BEFORE the human_approval node — state is serialised here
        compile_kwargs["interrupt_before"] = ["human_approval"]

    return builder.compile(**compile_kwargs)


# Module-level graph for local dev and LangGraph Cloud deployment.
# Uses MemorySaver so the module is importable without a running Postgres instance.
graph = build_graph(checkpointer=get_sync_checkpointer())
