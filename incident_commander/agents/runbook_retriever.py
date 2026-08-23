"""Runbook Retriever node — async, structured output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from incident_commander.agents.base import load_prompt, run_tool_loop
from incident_commander.core.constants import AgentRole
from incident_commander.core.logging import get_logger
from incident_commander.core.output_models import RunbookRetrieverOutput
from incident_commander.services.llm_factory import get_llm
from incident_commander.tools.langchain_tools import INVESTIGATION_TOOLS

logger = get_logger(__name__)


async def runbook_retriever_node(state: dict[str, Any]) -> dict[str, Any]:
    """Search runbooks and return structured findings."""
    logger.info("runbook_retriever.start", incident=state.get("incident_id"))

    tool_map = {t.name: t for t in INVESTIGATION_TOOLS}
    tool_llm = get_llm().bind_tools(INVESTIGATION_TOOLS)

    messages = await run_tool_loop(
        llm=tool_llm,
        messages=[
            SystemMessage(content=load_prompt("runbook_retriever")),
            HumanMessage(
                content=(
                    f"Find runbooks for:\n"
                    f"**Title:** {state.get('title', '')}\n"
                    f"**Service:** {state.get('affected_service', '')}\n"
                    f"**Description:** {state.get('description', '')}"
                )
            ),
        ],
        tool_map=tool_map,
    )

    synthesis_llm = get_llm().with_structured_output(RunbookRetrieverOutput)
    tool_results = "\n".join(
        m.content for m in messages if hasattr(m, "tool_call_id")
    )
    output: RunbookRetrieverOutput = await synthesis_llm.ainvoke(
        [
            SystemMessage(content=load_prompt("runbook_retriever")),
            HumanMessage(
                content=(
                    f"Synthesise runbook search results:\n\n"
                    f"{tool_results or 'No tool results.'}"
                )
            ),
        ]
    )

    findings = output.findings
    if not findings and output.best_runbook_title:
        findings = [f"Best match: {output.best_runbook_title}"]

    return {
        "runbook_findings": findings,
        "audit_trail": [
            {
                "agent": AgentRole.RUNBOOK_RETRIEVER,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "best_runbook_id": output.best_runbook_id,
                "estimated_resolution_minutes": output.estimated_resolution_minutes,
            }
        ],
    }
