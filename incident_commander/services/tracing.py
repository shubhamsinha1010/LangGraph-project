"""LangSmith tracing configuration.

When LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY is set, every LLM call,
tool invocation, and graph step is automatically traced end-to-end in LangSmith.

This module provides:
  - configure_tracing(): call once at startup to enable tracing
  - run_name_config(): returns a RunnableConfig with a meaningful run_name
    so each node appears with a readable label in the LangSmith trace tree
    instead of generic UUIDs
  - get_langsmith_run_url(): retrieves the LangSmith trace URL for an incident
    so it can be surfaced via the API
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.runnables import RunnableConfig

from incident_commander.core.config import get_settings
from incident_commander.core.logging import get_logger

logger = get_logger(__name__)


def configure_tracing() -> None:
    """Enable LangSmith tracing by setting the required environment variables.

    Called once at FastAPI startup (lifespan). Safe to call multiple times.
    """
    settings = get_settings()
    if not settings.langchain_tracing_v2:
        logger.info("tracing.disabled")
        return
    if not settings.langchain_api_key:
        logger.warning("tracing.enabled_but_no_api_key — tracing will not work")
        return

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    logger.info("tracing.enabled", project=settings.langchain_project)


def run_name_config(node_name: str, incident_id: str) -> RunnableConfig:
    """Build a RunnableConfig that annotates this node's run in LangSmith.

    Without this, all nodes appear as their function name in the trace.
    With this, the trace tree shows e.g. 'log_analyst [INC-abc123]' making
    multi-incident traces readable at a glance.
    """
    return RunnableConfig(
        run_name=f"{node_name} [{incident_id}]",
        tags=["incident-commander", node_name],
        metadata={"incident_id": incident_id, "node": node_name},
    )


def get_langsmith_run_url(incident_id: str) -> str | None:
    """Retrieve the LangSmith trace URL for an incident run.

    Returns None if tracing is disabled or the run is not yet available.
    The URL is constructed from the project and thread_id convention used
    by LangSmith's LangGraph integration.
    """
    settings = get_settings()
    if not settings.langchain_tracing_v2 or not settings.langchain_api_key:
        return None

    # LangSmith URL pattern for LangGraph threads
    project = settings.langchain_project
    return (
        f"https://smith.langchain.com/o/traces?"
        f"project={project}&filter=thread_id%3D{incident_id}"
    )
