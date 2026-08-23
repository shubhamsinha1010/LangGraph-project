"""Application configuration loaded from environment variables via pydantic-settings.

Single source of truth for all config — never read os.environ directly elsewhere.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", description="LLM base URL"
    )
    llm_model: str = Field(default="gpt-4o-mini")
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_retries: int = Field(default=3, ge=1)

    # Checkpointing
    checkpoint_backend: str = Field(default="memory", pattern="^(memory|postgres)$")
    database_url: str = Field(default="")

    # API
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_debug: bool = Field(default=False)
    api_secret_key: str = Field(default="change-me-in-production")

    # LangSmith
    langchain_tracing_v2: bool = Field(default=False)
    langchain_api_key: str = Field(default="")
    langchain_project: str = Field(default="incident-commander")

    # App behaviour
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    max_investigation_cycles: int = Field(default=5, ge=1, le=20)
    rollback_enabled: bool = Field(default=True)

    @field_validator("checkpoint_backend")
    @classmethod
    def validate_checkpoint_backend(cls, v: str) -> str:
        if v == "postgres":
            # Defer the database_url check to runtime to allow env override ordering
            pass
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the application settings singleton. Cached after first call."""
    return Settings()
