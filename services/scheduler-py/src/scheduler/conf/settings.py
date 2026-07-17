"""Environment-only, non-secret scheduler configuration."""

from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SchedulerSettings(BaseSettings):
    """Configuration validated before later transport adapters are started."""

    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_",
        case_sensitive=False,
        frozen=True,
        extra="forbid",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    service_bearer_token: SecretStr | None = None
    callback_service_token: SecretStr | None = None
    callback_base_url: AnyHttpUrl | None = None
    request_queue: str = "scheduler.requests"
    result_queue: str = "scheduler.results"
    solver_time_limit_seconds: int = Field(default=30, gt=0)
    queue_size_protection_limit: int = Field(default=100, gt=0)

    @model_validator(mode="after")
    def require_production_service_configuration(self) -> "SchedulerSettings":
        """Production needs credentials and a callback destination before it can start."""
        token_missing = (
            self.service_bearer_token is None
            or not self.service_bearer_token.get_secret_value().strip()
        )
        callback_token_missing = (
            self.callback_service_token is None
            or not self.callback_service_token.get_secret_value().strip()
        )
        if self.environment == "production" and (
            token_missing
            or callback_token_missing
            or self.callback_base_url is None
        ):
            raise ValueError(
                "production requires SCHEDULER_SERVICE_BEARER_TOKEN, "
                "SCHEDULER_CALLBACK_SERVICE_TOKEN, and SCHEDULER_CALLBACK_BASE_URL"
            )
        return self
