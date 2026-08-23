"""Metrics Analyst node."""

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from incident_commander.agents.base import load_prompt, parse_json_from_message
from incident_commander.core.constants import AgentRole
from incident_commander.core.logging import get_logger
from incident_commander.services.llm_factory import get_llm
from incident_commander.tools.langchain_tools import INVESTIGATION_TOOLS

logger = get_logger(__name__)


def metrics_analyst_node(state: dict[str, Any]) -> dict[str, Any]:
    """Invoke the metrics analyst and return metrics_findings updates."""
    service = state.get("affected_service", "unknown")
    logger.info("metrics_analyst.start", service=service)

    llm = get_llm().bind_tools(INVESTIGATION_TOOLS)
    system_prompt = load_prompt("metrics_analyst")

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=(
                f"Investigate performance metrics for:\n\n"
                f"**Service:** {service}\n"
                f"**Incident:** {state.get('title', '')}\n"
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
    if not findings:
        findings = [f"Metrics analyst completed for {service}."]

    return {
        "metrics_findings": findings,
        "audit_trail": [
            {
                "agent": AgentRole.METRICS_ANALYST,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "findings_count": len(findings),
            }
        ],
    }
