"""Runbook Retriever node."""

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from incident_commander.agents.base import load_prompt, parse_json_from_message
from incident_commander.core.constants import AgentRole
from incident_commander.core.logging import get_logger
from incident_commander.services.llm_factory import get_llm
from incident_commander.tools.langchain_tools import INVESTIGATION_TOOLS

logger = get_logger(__name__)


def runbook_retriever_node(state: dict[str, Any]) -> dict[str, Any]:
    """Invoke the runbook retriever and return runbook_findings updates."""
    logger.info("runbook_retriever.start", incident=state.get("incident_id"))

    llm = get_llm().bind_tools(INVESTIGATION_TOOLS)
    system_prompt = load_prompt("runbook_retriever")

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=(
                f"Find runbooks for this incident:\n\n"
                f"**Title:** {state.get('title', '')}\n"
                f"**Service:** {state.get('affected_service', '')}\n"
                f"**Description:** {state.get('description', '')}"
            )
        ),
    ]

    tool_map = {t.name: t for t in INVESTIGATION_TOOLS}
    for _ in range(5):
        response = llm.invoke(messages)
        messages.append(response)
        if not getattr(response, "tool_calls", None):
            break
        for tc in response.tool_calls:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn:
                tool_output = tool_fn.invoke(tc["args"])
                from langchain_core.messages import ToolMessage
                messages.append(
                    ToolMessage(content=str(tool_output), tool_call_id=tc["id"])
                )

    parsed = parse_json_from_message(response)
    findings: list[str] = parsed.get("findings", [])
    if not findings and parsed.get("best_runbook_title"):
        findings = [f"Matched runbook: {parsed['best_runbook_title']}"]

    return {
        "runbook_findings": findings,
        "audit_trail": [
            {
                "agent": AgentRole.RUNBOOK_RETRIEVER,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "best_runbook": parsed.get("best_runbook_id"),
            }
        ],
    }
