"""Supervisor node — routes the investigation based on current state."""

from datetime import datetime, timezone
from typing import Any

from incident_commander.core.config import get_settings
from incident_commander.core.constants import (
    AgentRole,
    IncidentStatus,
    RoutingDecision,
)
from incident_commander.core.exceptions import MaxCyclesExceededError
from incident_commander.core.logging import get_logger

logger = get_logger(__name__)


def supervisor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Assess current state and decide what the next step should be.

    This is a pure routing function — it does not call an LLM.
    Routing logic lives here (not scattered in edges) for testability.
    """
    settings = get_settings()
    cycles = state.get("investigation_cycles", 0)
    routing = state.get("routing_decision")
    status = state.get("status", IncidentStatus.OPEN)

    logger.info(
        "supervisor.routing",
        incident=state.get("incident_id"),
        cycles=cycles,
        routing=routing,
        status=status,
    )

    # Guard: prevent infinite investigation loops
    if cycles >= settings.max_investigation_cycles:
        logger.warning(
            "supervisor.max_cycles_exceeded",
            incident=state.get("incident_id"),
            cycles=cycles,
        )
        return {
            "routing_decision": RoutingDecision.ESCALATE,
            "status": IncidentStatus.INVESTIGATING,
            "audit_trail": [
                {
                    "agent": AgentRole.SUPERVISOR,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "decision": RoutingDecision.ESCALATE,
                    "reason": "max_cycles_exceeded",
                }
            ],
        }

    # Initial entry — start investigation
    if status == IncidentStatus.OPEN or routing is None:
        return {
            "routing_decision": RoutingDecision.INVESTIGATE,
            "status": IncidentStatus.INVESTIGATING,
            "investigation_cycles": cycles + 1,
            "audit_trail": [
                {
                    "agent": AgentRole.SUPERVISOR,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "decision": RoutingDecision.INVESTIGATE,
                    "reason": "initial_entry",
                }
            ],
        }

    # Planner said more investigation needed
    if routing == RoutingDecision.INVESTIGATE:
        return {
            "investigation_cycles": cycles + 1,
            "audit_trail": [
                {
                    "agent": AgentRole.SUPERVISOR,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "decision": RoutingDecision.INVESTIGATE,
                    "reason": "planner_requested_more",
                    "cycle": cycles + 1,
                }
            ],
        }

    # Planner produced a destructive plan — wait for human
    if routing == RoutingDecision.AWAIT_APPROVAL:
        return {
            "status": IncidentStatus.AWAITING_APPROVAL,
            "audit_trail": [
                {
                    "agent": AgentRole.SUPERVISOR,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "decision": RoutingDecision.AWAIT_APPROVAL,
                    "reason": "destructive_action_proposed",
                }
            ],
        }

    return {}


def route_after_supervisor(state: dict[str, Any]) -> str:
    """Conditional edge — returns the name of the next node."""
    routing = state.get("routing_decision")

    if routing == RoutingDecision.INVESTIGATE:
        return "investigate"
    if routing == RoutingDecision.AWAIT_APPROVAL:
        return "human_approval"
    if routing == RoutingDecision.EXECUTE:
        return "execute"
    if routing == RoutingDecision.RESOLVE:
        return "resolve"
    if routing == RoutingDecision.ESCALATE:
        return "escalate"
    return "resolve"


def route_after_planner(state: dict[str, Any]) -> str:
    """Conditional edge after the planner runs."""
    routing = state.get("routing_decision")
    if routing == RoutingDecision.INVESTIGATE:
        return "supervisor"
    if routing == RoutingDecision.AWAIT_APPROVAL:
        return "human_approval"
    if routing == RoutingDecision.EXECUTE:
        return "executor"
    return "supervisor"


def route_after_executor(state: dict[str, Any]) -> str:
    """Conditional edge after execution."""
    result = state.get("execution_result", {})
    if result.get("success"):
        return "resolve"
    return "escalate"
