"""Resolver and escalation nodes — async."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from incident_commander.core.constants import AgentRole, IncidentStatus
from incident_commander.core.logging import get_logger

logger = get_logger(__name__)


async def resolver_node(state: dict[str, Any]) -> dict[str, Any]:
    """Mark the incident resolved and write a final summary."""
    incident_id = state.get("incident_id", "unknown")
    logger.info("resolver.resolving", incident=incident_id)

    execution = state.get("execution_result") or {}
    diagnosis = state.get("diagnosis", "See investigation findings.")

    summary = (
        f"Incident '{state.get('title', '')}' resolved.\n"
        f"Root cause: {diagnosis}\n"
        f"Action taken: {execution.get('action_taken', 'No destructive action required.')}\n"
        f"Result: {execution.get('result_summary', 'N/A')}"
    )

    return {
        "status": IncidentStatus.RESOLVED,
        "audit_trail": [
            {
                "agent": AgentRole.SUPERVISOR,
                "event": "resolved",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "summary": summary,
            }
        ],
    }


async def escalation_node(state: dict[str, Any]) -> dict[str, Any]:
    """Mark the incident as needing human escalation."""
    incident_id = state.get("incident_id", "unknown")
    logger.warning("escalation.triggered", incident=incident_id)

    return {
        "status": IncidentStatus.OPEN,
        "audit_trail": [
            {
                "agent": AgentRole.SUPERVISOR,
                "event": "escalated",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "reason": "automated_resolution_failed_or_exceeded_cycles",
            }
        ],
    }
