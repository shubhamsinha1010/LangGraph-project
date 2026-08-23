"""Log Analyst node — async, structured output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from incident_commander.agents.base import load_prompt, run_tool_loop
from incident_commander.core.constants import AgentRole
from incident_commander.core.logging import get_logger
from incident_commander.core.output_models import LogAnalystOutput
from incident_commander.services.llm_factory import get_llm
from incident_commander.services.tracing import run_name_config
from incident_commander.tools.langchain_tools import INVESTIGATION_TOOLS

logger = get_logger(__name__)


async def log_analyst_node(state: dict[str, Any]) -> dict[str, Any]:
    """Query error logs and return structured findings."""
    service = state.get("affected_service", "unknown")
    logger.info("log_analyst.start", service=service)

    incident_id = state.get("incident_id", "unknown")
    trace_cfg = run_name_config("log_analyst", incident_id)
    tool_map = {t.name: t for t in INVESTIGATION_TOOLS}
    tool_llm = get_llm().bind_tools(INVESTIGATION_TOOLS)

    messages = await run_tool_loop(
        llm=tool_llm,
        messages=[
            SystemMessage(content=load_prompt("log_analyst")),
            HumanMessage(
                content=(
                    f"Investigate logs for:\n"
                    f"**Title:** {state.get('title', '')}\n"
                    f"**Service:** {service}\n"
                    f"**Description:** {state.get('description', '')}\n\n"
                    f"Query the last 15 minutes of logs."
                )
            ),
        ],
        tool_map=tool_map,
    )

    # Structured synthesis pass — type-safe, no manual JSON parsing
    synthesis_llm = get_llm().with_structured_output(LogAnalystOutput)
    tool_results = "\n".join(
        m.content for m in messages if hasattr(m, "tool_call_id")
    )
    output: LogAnalystOutput = await synthesis_llm.ainvoke(
        [
            SystemMessage(content=load_prompt("log_analyst")),
            HumanMessage(
                content=(
                    f"Synthesise the following tool results into structured findings "
                    f"for service '{service}':\n\n{tool_results or 'No tool results.'}"
                )
            ),
        ]
    )

    return {
        "log_findings": output.findings,
        "audit_trail": [
            {
                "agent": AgentRole.LOG_ANALYST,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "findings_count": len(output.findings),
                "error_rate_pct": output.error_rate_pct,
            }
        ],
    }
