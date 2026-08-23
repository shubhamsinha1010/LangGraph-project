"""Executor node — carries out the approved action.

This node only runs after human approval has been recorded in state.
It enforces that guard at the node level as a defence-in-depth measure.
"""

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from incident_commander.agents.base import load_prompt, parse_json_from_message
from incident_commander.core.constants import AgentRole, IncidentStatus, RoutingDecision
from incident_commander.core.exceptions import ApprovalRequiredError
from incident_commander.core.logging import get_logger
from incident_commander.services.llm_factory import get_llm
from incident_commander.tools.langchain_tools import DESTRUCTIVE_TOOLS

logger = get_logger(__name__)


def executor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the approved action using the appropriate tool."""
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

    llm = get_llm().bind_tools(DESTRUCTIVE_TOOLS)
    system_prompt = load_prompt("executor")

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=(
                f"Execute the following approved action:\n\n"
                f"**Action type:** {approved_action.get('action_type')}\n"
                f"**Description:** {approved_action.get('description')}\n"
                f"**Service:** {approved_action.get('service')}\n"
                f"**Incident ID (use as task_id):** {incident_id}\n"
                f"**Approval notes:** {state.get('approval_notes', 'None')}\n\n"
                f"Call the appropriate tool now."
            )
        ),
    ]

    tool_map = {t.name: t for t in DESTRUCTIVE_TOOLS}
    tool_results: list[str] = []

    for _ in range(3):
        response = llm.invoke(messages)
        messages.append(response)
        if not getattr(response, "tool_calls", None):
            break
        for tc in response.tool_calls:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn:
                tool_output = tool_fn.invoke(tc["args"])
                tool_results.append(str(tool_output))
                from langchain_core.messages import ToolMessage
                messages.append(
                    ToolMessage(content=str(tool_output), tool_call_id=tc["id"])
                )

    parsed = parse_json_from_message(response)
    success = parsed.get("success", bool(tool_results))

    return {
        "execution_result": {
            "action_taken": parsed.get("action_taken", approved_action.get("description")),
            "tool_called": parsed.get("tool_called", "unknown"),
            "success": success,
            "result_summary": parsed.get("result_summary", "\n".join(tool_results)),
            "tool_outputs": tool_results,
        },
        "status": (
            IncidentStatus.RESOLVED if success else IncidentStatus.INVESTIGATING
        ),
        "routing_decision": (
            RoutingDecision.RESOLVE if success else RoutingDecision.ESCALATE
        ),
        "audit_trail": [
            {
                "agent": AgentRole.EXECUTOR,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "action": approved_action.get("action_type"),
                "success": success,
            }
        ],
    }
