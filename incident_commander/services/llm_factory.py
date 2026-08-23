"""LLM factory — provider-agnostic, cached, async-compatible.

All nodes use get_llm() which returns a ChatOpenAI instance.
ChatOpenAI natively supports both .invoke() (sync) and .ainvoke() (async).
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from incident_commander.core.config import get_settings
from incident_commander.core.exceptions import LLMError
from incident_commander.core.logging import get_logger

logger = get_logger(__name__)


def build_llm(
    *,
    model: str | None = None,
    temperature: float | None = None,
    streaming: bool = False,
) -> BaseChatModel:
    """Construct and return a chat model instance."""
    settings = get_settings()
    chosen_model = model or settings.llm_model
    chosen_temp = temperature if temperature is not None else settings.llm_temperature

    logger.info("building_llm", model=chosen_model, temperature=chosen_temp, streaming=streaming)

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


@lru_cache(maxsize=4)
def get_llm(model: str | None = None, streaming: bool = False) -> BaseChatModel:
    """Cached LLM getter — same model+streaming combo returns the same instance.

    The returned instance supports both .invoke() and .ainvoke() natively.
    """
    return build_llm(model=model, streaming=streaming)
