"""Supervisor node and routing functions — async."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from incident_commander.core.config import get_settings
from incident_commander.core.constants import (
    AgentRole,
    IncidentStatus,
    RoutingDecision,
)
from incident_commander.core.logging import get_logger
from incident_commander.core.state import initial_state

logger = get_logger(__name__)


async def supervisor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Assess current state and decide the next step. Pure routing — no LLM."""
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

    if cycles >= settings.max_investigation_cycles:
        logger.warning("supervisor.max_cycles_exceeded", incident=state.get("incident_id"))
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
    routing = state.get("routing_decision")
    if routing == RoutingDecision.INVESTIGATE:
        return "supervisor"
    if routing == RoutingDecision.AWAIT_APPROVAL:
        return "human_approval"
    if routing == RoutingDecision.EXECUTE:
        return "executor"
    return "supervisor"


def route_after_executor(state: dict[str, Any]) -> str:
    result = state.get("execution_result", {})
    if result.get("success"):
        return "resolve"
    return "escalate"
