"""Planner node — synthesises all findings into a diagnosis and action plan."""

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from incident_commander.agents.base import load_prompt, parse_json_from_message
from incident_commander.core.constants import AgentRole, IncidentStatus, RoutingDecision
from incident_commander.core.logging import get_logger
from incident_commander.services.llm_factory import get_llm

logger = get_logger(__name__)


def planner_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synthesise all investigation findings into a diagnosis and action plan."""
    logger.info("planner.start", incident=state.get("incident_id"))

    llm = get_llm()
    system_prompt = load_prompt("planner")

    # Build a structured summary of all findings for the planner
    all_findings = _format_findings(state)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=(
                f"Synthesise the following investigation findings:\n\n"
                f"**Incident:** {state.get('title', '')}\n"
                f"**Service:** {state.get('affected_service', '')}\n"
                f"**Severity:** {state.get('severity', '')}\n\n"
                f"{all_findings}"
            )
        ),
    ]

    response = llm.invoke(messages)
    parsed = parse_json_from_message(response)

    diagnosis = parsed.get("diagnosis", "Unable to determine root cause.")
    confidence = float(parsed.get("confidence", 0.5))
    proposed_actions = parsed.get("proposed_actions", [])
    needs_more = parsed.get("needs_more_investigation", confidence < 0.5)

    # Determine routing + auto-approve non-destructive top action
    auto_approved: dict | None = None
    if needs_more:
        routing = RoutingDecision.INVESTIGATE
    elif proposed_actions and any(a.get("is_destructive") for a in proposed_actions):
        routing = RoutingDecision.AWAIT_APPROVAL
    elif proposed_actions:
        # Non-destructive top action — auto-approve, skip HITL gate
        routing = RoutingDecision.EXECUTE
        top = min(proposed_actions, key=lambda a: a.get("priority", 99))
        auto_approved = top
    else:
        routing = RoutingDecision.RESOLVE

    return {
        "diagnosis": diagnosis,
        "confidence": confidence,
        "proposed_actions": proposed_actions,
        "needs_more_investigation": needs_more,
        "routing_decision": routing,
        "approved_action": auto_approved,
        "approval_notes": "auto-approved (non-destructive action)" if auto_approved else "",
        "status": (
            IncidentStatus.AWAITING_APPROVAL
            if routing == RoutingDecision.AWAIT_APPROVAL
            else IncidentStatus.INVESTIGATING
        ),
        "audit_trail": [
            {
                "agent": AgentRole.PLANNER,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "diagnosis": diagnosis[:100],
                "confidence": confidence,
                "routing": routing,
            }
        ],
    }


def _format_findings(state: dict[str, Any]) -> str:
    sections = []
    for key, label in [
        ("log_findings", "Log Findings"),
        ("metrics_findings", "Metrics Findings"),
        ("change_findings", "Change Findings"),
        ("runbook_findings", "Runbook Findings"),
    ]:
        items = state.get(key, [])
        if items:
            bullet = "\n".join(f"  - {f}" for f in items)
            sections.append(f"### {label}\n{bullet}")
    return "\n\n".join(sections) if sections else "No findings available."
