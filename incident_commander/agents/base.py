"""Base agent helper.

Provides shared utilities for prompt loading and structured output parsing.
Following DRY — shared logic lives here, not duplicated in every node.
"""

import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser

from incident_commander.core.logging import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a markdown prompt template by filename stem."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def parse_json_from_message(message: AIMessage) -> dict:
    """Extract JSON from an AIMessage, stripping markdown fences if present."""
    content = message.content
    if isinstance(content, list):
        content = " ".join(
            block["text"] if isinstance(block, dict) else str(block)
            for block in content
        )
    content = str(content).strip()
    # Strip ```json ... ``` fences
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("json_parse_failed", raw=content[:200])
        return {}
