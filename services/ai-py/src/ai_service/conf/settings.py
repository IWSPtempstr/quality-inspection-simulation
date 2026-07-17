from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_SERVICE_",
        case_sensitive=False,
        extra="ignore",
    )

    service_bearer_token: str | None = Field(default=None, min_length=8)
    environment: str = Field(default="development", min_length=1)
    log_level: str = Field(default="INFO", min_length=1)
    prompt_directory: Path = Field(default=Path("prompts"))
    llm_timeout_seconds: float = Field(default=10.0, gt=0)
    default_model: str = Field(default="disabled")
    memory_recent_ttl_seconds: int = Field(default=24 * 60 * 60, gt=0)
    memory_summary_ttl_seconds: int = Field(default=7 * 24 * 60 * 60, gt=0)
    memory_max_turns: int = Field(default=8, gt=0)
    memory_max_tokens: int = Field(default=6000, gt=0)
    redact_fields: tuple[str, ...] = (
        "authorization",
        "token",
        "password",
        "secret",
        "source_body",
        "query",
    )

    @model_validator(mode="after")
    def require_production_service_token(self) -> AIServiceSettings:
        token_missing = self.service_bearer_token is None or not self.service_bearer_token.strip()
        if self.environment == "production" and token_missing:
            raise ValueError("production requires AI_SERVICE_SERVICE_BEARER_TOKEN")
        return self

    @property
    def app_env(self) -> str:
        return self.environment

    @property
    def prompt_dir(self) -> Path:
        return self.prompt_directory

    @property
    def llm_model(self) -> str:
        return self.default_model


Settings = AIServiceSettings


@lru_cache(maxsize=1)
def get_settings() -> AIServiceSettings:
    return AIServiceSettings()
