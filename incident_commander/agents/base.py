"""Base agent helpers — shared across all nodes.

DRY: shared utilities live here, not duplicated per node.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _invoke_llm_with_retry(llm: Any, messages: list[BaseMessage]) -> Any:
    """Invoke the LLM with per-call retry.

    Retries only the LLM call — NOT the entire tool loop.
    This prevents already-completed tool calls from being re-executed on retry,
    which could cause duplicate side effects (idempotency violation).
    """
    return await llm.ainvoke(messages)


async def run_tool_loop(
    llm: Any,
    messages: list[BaseMessage],
    tool_map: dict[str, Any],
    max_rounds: int = 5,
) -> list[BaseMessage]:
    """Async tool-use loop with per-LLM-call retry.

    Each LLM invocation is individually retried on transient failure (rate
    limit, timeout). Tool executions are NOT retried — if a tool fails, the
    error is captured as a ToolMessage so the LLM can decide how to proceed.

    Args:
        llm: A bound LLM (already has tools attached via .bind_tools()).
        messages: Initial message list (system + human prompts).
        tool_map: Dict mapping tool name → callable tool.
        max_rounds: Maximum tool-call rounds before stopping.
    """
    msgs = list(messages)
    for _ in range(max_rounds):
        response = await _invoke_llm_with_retry(llm, msgs)
        msgs.append(response)

        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            break

        for tc in tool_calls:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn is None:
                logger.warning("tool_not_found", tool=tc["name"])
                output = f"Error: tool '{tc['name']}' not available."
            else:
                try:
                    output = tool_fn.invoke(tc["args"])
                except Exception as exc:
                    logger.warning("tool_call_failed", tool=tc["name"], error=str(exc))
                    output = f"Tool error ({tc['name']}): {exc}"
            msgs.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))

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
