"""Change Analyst node — async, structured output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from incident_commander.agents.base import load_prompt, run_tool_loop
from incident_commander.core.constants import AgentRole
from incident_commander.core.logging import get_logger
from incident_commander.core.output_models import ChangeAnalystOutput
from incident_commander.services.llm_factory import get_llm
from incident_commander.tools.langchain_tools import INVESTIGATION_TOOLS

logger = get_logger(__name__)


async def change_analyst_node(state: dict[str, Any]) -> dict[str, Any]:
    """Query recent changes and return structured findings."""
    service = state.get("affected_service", "unknown")
    logger.info("change_analyst.start", service=service)

    tool_map = {t.name: t for t in INVESTIGATION_TOOLS}
    tool_llm = get_llm().bind_tools(INVESTIGATION_TOOLS)

    messages = await run_tool_loop(
        llm=tool_llm,
        messages=[
            SystemMessage(content=load_prompt("change_analyst")),
            HumanMessage(
                content=(
                    f"Investigate recent changes for:\n"
                    f"**Service:** {service}\n"
                    f"**Incident:** {state.get('title', '')}\n"
                    f"Check the last 24 hours."
                )
            ),
        ],
        tool_map=tool_map,
    )

    synthesis_llm = get_llm().with_structured_output(ChangeAnalystOutput)
    tool_results = "\n".join(
        m.content for m in messages if hasattr(m, "tool_call_id")
    )
    output: ChangeAnalystOutput = await synthesis_llm.ainvoke(
        [
            SystemMessage(content=load_prompt("change_analyst")),
            HumanMessage(
                content=(
                    f"Synthesise change data for '{service}':\n\n"
                    f"{tool_results or 'No tool results.'}"
                )
            ),
        ]
    )

    return {
        "change_findings": output.findings,
        "audit_trail": [
            {
                "agent": AgentRole.CHANGE_ANALYST,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "findings_count": len(output.findings),
                "culprit_change_id": output.most_likely_culprit_change_id,
                "correlation_confidence": output.correlation_confidence,
            }
        ],
    }
