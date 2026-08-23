"""Base agent helpers.

Shared utilities for all nodes — prompt loading, async tool-use loop, retry.
DRY: logic lives here once, not repeated in every node.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from incident_commander.core.logging import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a markdown prompt template by filename stem."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def run_tool_loop(
    llm: Any,
    messages: list[BaseMessage],
    tool_map: dict[str, Any],
    max_rounds: int = 5,
) -> list[BaseMessage]:
    """Async tool-use loop with automatic retry on failure.

    Runs until the LLM stops requesting tools or max_rounds is reached.
    All tool calls are executed and results appended as ToolMessages.
    Retries the entire loop on transient LLM errors (rate limit, timeout).
    """
    msgs = list(messages)
    for _ in range(max_rounds):
        response = await llm.ainvoke(msgs)
        msgs.append(response)

        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            break

        for tc in tool_calls:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn is None:
                logger.warning("tool_not_found", tool=tc["name"])
                continue
            try:
                output = tool_fn.invoke(tc["args"])
            except Exception as exc:
                logger.warning("tool_call_failed", tool=tc["name"], error=str(exc))
                output = f"Tool error: {exc}"
            msgs.append(
                ToolMessage(content=str(output), tool_call_id=tc["id"])
            )

    return msgs


def format_findings_for_planner(state: dict[str, Any]) -> str:
    """Format all investigation findings into a planner-readable summary."""
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
    return "\n\n".join(sections) if sections else "No findings available yet."
