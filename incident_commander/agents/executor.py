"""Executor node — async, structured output, records to long-term memory."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from incident_commander.agents.base import load_prompt, run_tool_loop
from incident_commander.core.constants import AgentRole, IncidentStatus, RoutingDecision
from incident_commander.core.exceptions import ApprovalRequiredError
from incident_commander.core.logging import get_logger
from incident_commander.core.output_models import ExecutorOutput
from incident_commander.services.llm_factory import get_llm
from incident_commander.services.memory_store import (
    IncidentMemoryEntry,
    record_incident_resolution,
)
from incident_commander.tools.langchain_tools import DESTRUCTIVE_TOOLS

logger = get_logger(__name__)


async def executor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the approved action and record the outcome to long-term memory."""
    approved_action = state.get("approved_action")
    incident_id = state.get("incident_id", "unknown")

    if not approved_action:
        raise ApprovalRequiredError("execute", incident_id)

    logger.info(
        "executor.start",
        incident=incident_id,
        action=approved_action.get("action_type"),
        service=approved_action.get("service"),
    )

    tool_map = {t.name: t for t in DESTRUCTIVE_TOOLS}
    tool_llm = get_llm().bind_tools(DESTRUCTIVE_TOOLS)

    messages = await run_tool_loop(
        llm=tool_llm,
        messages=[
            SystemMessage(content=load_prompt("executor")),
            HumanMessage(
                content=(
                    f"Execute the approved action:\n\n"
                    f"**Action type:** {approved_action.get('action_type')}\n"
                    f"**Description:** {approved_action.get('description')}\n"
                    f"**Service:** {approved_action.get('service')}\n"
                    f"**Incident ID (use as task_id):** {incident_id}\n"
                    f"**Approval notes:** {state.get('approval_notes', 'None')}"
                )
            ),
        ],
        tool_map=tool_map,
        max_rounds=3,
    )

    synthesis_llm = get_llm().with_structured_output(ExecutorOutput)
    tool_results = "\n".join(
        m.content for m in messages if hasattr(m, "tool_call_id")
    )
    output: ExecutorOutput = await synthesis_llm.ainvoke(
        [
            SystemMessage(content=load_prompt("executor")),
            HumanMessage(
                content=(
                    f"Summarise the execution result:\n\n"
                    f"Action: {approved_action.get('description')}\n"
                    f"Tool outputs:\n{tool_results or 'No tool outputs.'}"
                )
            ),
        ]
    )

    # Record outcome to long-term memory so future incidents benefit
    record_incident_resolution(
        IncidentMemoryEntry(
            incident_id=incident_id,
            service=approved_action.get("service", "unknown"),
            diagnosis=state.get("diagnosis", ""),
            action_taken=output.action_taken,
            resolved=output.success,
            resolution_minutes=0,  # could be computed from audit_trail timestamps
        )
    )

    return {
        "execution_result": output.model_dump(),
        "status": (
            IncidentStatus.RESOLVED if output.success else IncidentStatus.INVESTIGATING
        ),
        "routing_decision": (
            RoutingDecision.RESOLVE if output.success else RoutingDecision.ESCALATE
        ),
        "audit_trail": [
            {
                "agent": AgentRole.EXECUTOR,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "action": approved_action.get("action_type"),
                "success": output.success,
                "recorded_to_memory": True,
            }
        ],
    }
