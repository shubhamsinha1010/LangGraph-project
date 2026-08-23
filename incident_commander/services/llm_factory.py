"""LLM factory — provider-agnostic, async-compatible.

Design note on caching:
  ChatOpenAI instances are mutable — they carry callback state that can be
  mutated during invocation. Sharing a single cached instance across parallel
  async nodes risks race conditions on that internal state.

  Solution: cache the *configuration* (model, temperature, streaming) and
  construct a fresh instance per call, which is cheap. The underlying HTTP
  client pool IS shared via the openai library's module-level singleton, so
  we get connection reuse without sharing mutable LLM state.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from incident_commander.core.config import get_settings
from incident_commander.core.exceptions import LLMError
from incident_commander.core.logging import get_logger

logger = get_logger(__name__)


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
    streaming: bool = False,
) -> BaseChatModel:
    """Build and return a fresh ChatOpenAI instance per call.

    Fresh instances share the underlying HTTP connection pool (openai-level
    singleton) but do NOT share mutable callback / metadata state, making
    them safe for concurrent async invocation from parallel graph nodes.
    """
    settings = get_settings()
    chosen_model = model or settings.llm_model
    chosen_temp = temperature if temperature is not None else settings.llm_temperature

    logger.debug("building_llm", model=chosen_model, temperature=chosen_temp, streaming=streaming)

    try:
        return ChatOpenAI(
            model=chosen_model,
            temperature=chosen_temp,
            streaming=streaming,
            max_retries=settings.llm_max_retries,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    except Exception as exc:
        raise LLMError(f"Failed to construct LLM '{chosen_model}': {exc}") from exc
