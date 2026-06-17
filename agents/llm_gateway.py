from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from config.settings import AgentModelConfig


class LlmClientProtocol(Protocol):
    def chat_json(
        self,
        config: AgentModelConfig,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class LlmGatewayResult:
    content: dict[str, Any]
    mode: str
    fallback_used: bool
    error: str | None
    metadata: dict[str, Any]


class LlmGateway:
    """Normalize optional LLM calls into deterministic agent results."""

    def __init__(
        self,
        agent_configs: Mapping[str, AgentModelConfig],
        *,
        retry_sleep_seconds: float = 1.0,
    ) -> None:
        self.agent_configs = agent_configs
        self.retry_sleep_seconds = retry_sleep_seconds

    def chat_json(
        self,
        *,
        agent_name: str,
        client: LlmClientProtocol | None,
        messages: list[dict[str, str]],
        fallback: Callable[[str | None], dict[str, Any]],
        required_keys: set[str] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmGatewayResult:
        config = self.agent_configs.get(agent_name)
        if not client or not config or not config.api_key:
            return self._fallback_result(fallback, None, metadata={})

        system_prompt, user_message = self._extract_messages(messages)
        last_error: str | None = None
        for attempt in range(2):
            try:
                llm_result = client.chat_json(
                    config=config,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = llm_result["content"]
                missing_keys = self._missing_required_keys(content, required_keys)
                if missing_keys:
                    last_error = f"missing required LLM keys: {', '.join(missing_keys)}"
                    return self._fallback_result(
                        fallback,
                        last_error,
                        metadata={
                            "llm_called": True,
                            "model": llm_result.get("model", config.model),
                            "token_usage": llm_result.get("token_usage", {}),
                            "fallback_used": True,
                            "error": last_error,
                            "retry_attempt": attempt,
                        },
                    )
                return LlmGatewayResult(
                    content=content,
                    mode="llm",
                    fallback_used=False,
                    error=None,
                    metadata={
                        "llm_called": True,
                        "model": llm_result["model"],
                        "token_usage": llm_result.get("token_usage", {}),
                        "fallback_used": False,
                        "retry_attempt": attempt,
                    },
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt == 0:
                    time.sleep(self.retry_sleep_seconds)

        return self._fallback_result(
            fallback,
            last_error,
            metadata={
                "llm_called": True,
                "model": config.model,
                "token_usage": None,
                "fallback_used": True,
                "error": last_error,
                "retry_attempt": 1,
            },
        )

    def raw_chat_json(
        self,
        *,
        agent_name: str,
        client: LlmClientProtocol,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Run a configured LLM JSON call without fallback wrapping.

        This is for callers that already have batch-level fallback semantics but
        still need the gateway to own model lookup and message normalization.
        """
        config = self.agent_configs[agent_name]
        system_prompt, user_message = self._extract_messages(messages)
        return client.chat_json(
            config=config,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _fallback_result(
        self,
        fallback: Callable[[str | None], dict[str, Any]],
        error: str | None,
        *,
        metadata: dict[str, Any],
    ) -> LlmGatewayResult:
        return LlmGatewayResult(
            content=fallback(error),
            mode="deterministic_fallback",
            fallback_used=True,
            error=error,
            metadata=metadata,
        )

    def _extract_messages(self, messages: list[dict[str, str]]) -> tuple[str, str]:
        system_prompt = ""
        user_message = ""
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "system" and not system_prompt:
                system_prompt = content
            elif role == "user" and not user_message:
                user_message = content
        return system_prompt, user_message

    def _missing_required_keys(
        self,
        content: Any,
        required_keys: set[str] | None,
    ) -> list[str]:
        if not required_keys:
            return []
        if not isinstance(content, dict):
            return sorted(required_keys)
        return sorted(key for key in required_keys if key not in content)
