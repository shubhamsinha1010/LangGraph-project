"""Planner node — async, fully structured output, long-term memory aware."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from incident_commander.agents.base import format_findings_for_planner, load_prompt
from incident_commander.core.constants import AgentRole, IncidentStatus, RoutingDecision
from incident_commander.core.logging import get_logger
from incident_commander.core.output_models import PlannerOutput
from incident_commander.services.llm_factory import get_llm
from incident_commander.services.memory_store import recall_past_incidents

logger = get_logger(__name__)


async def planner_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synthesise all findings into a structured diagnosis and action plan.

    Also queries long-term memory for past incidents on the same service,
    giving the planner historical context for faster, more confident diagnosis.
    """
    incident_id = state.get("incident_id", "unknown")
    service = state.get("affected_service", "unknown")
    logger.info("planner.start", incident=incident_id)

    # Long-term memory — past incidents for this service
    past_incidents = recall_past_incidents(service, limit=3)
    past_context = ""
    if past_incidents:
        past_context = "\n### Past Incidents (same service)\n" + "\n".join(
            f"  - [{p['timestamp'][:10]}] {p['diagnosis']} → fixed by: {p['action_taken']}"
            for p in past_incidents
        )

    findings_summary = format_findings_for_planner(state)

    llm = get_llm().with_structured_output(PlannerOutput)
    output: PlannerOutput = await llm.ainvoke(
        [
            SystemMessage(content=load_prompt("planner")),
            HumanMessage(
                content=(
                    f"**Incident:** {state.get('title', '')}\n"
                    f"**Service:** {service}\n"
                    f"**Severity:** {state.get('severity', '')}\n\n"
                    f"{findings_summary}"
                    f"{past_context}"
                )
            ),
        ]
    )

    # Routing logic
    auto_approved: dict | None = None
    if output.needs_more_investigation:
        routing = RoutingDecision.INVESTIGATE
    elif output.proposed_actions and any(
        a.is_destructive for a in output.proposed_actions
    ):
        routing = RoutingDecision.AWAIT_APPROVAL
    elif output.proposed_actions:
        routing = RoutingDecision.EXECUTE
        top = min(output.proposed_actions, key=lambda a: a.priority)
        auto_approved = top.model_dump()
    else:
        routing = RoutingDecision.RESOLVE

    return {
        "diagnosis": output.diagnosis,
        "confidence": output.confidence,
        "proposed_actions": [a.model_dump() for a in output.proposed_actions],
        "needs_more_investigation": output.needs_more_investigation,
        "routing_decision": routing,
        "approved_action": auto_approved,
        "approval_notes": "auto-approved (non-destructive)" if auto_approved else "",
        "status": (
            IncidentStatus.AWAITING_APPROVAL
            if routing == RoutingDecision.AWAIT_APPROVAL
            else IncidentStatus.INVESTIGATING
        ),
        "audit_trail": [
            {
                "agent": AgentRole.PLANNER,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "diagnosis": output.diagnosis[:100],
                "confidence": output.confidence,
                "routing": routing,
                "used_past_incidents": len(past_incidents),
            }
        ],
    }
