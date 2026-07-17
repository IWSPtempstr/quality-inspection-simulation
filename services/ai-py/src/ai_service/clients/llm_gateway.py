from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_service.core.errors import StructuredOutputError
from ai_service.entities.validation import ensure_citation_integrity

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class NormalizedLLMResponse:
    text: str
    payload: dict[str, Any] | list[Any]


@dataclass(frozen=True)
class GatewayPrompt:
    system_prompt: str
    user_prompt: str


class StructuredLLMGateway:
    """A1 boundary for normalized structured LLM results."""

    def decode(self, payload: str | bytes | dict[str, Any], model_type: type[ModelT]) -> ModelT:
        adapter = TypeAdapter(model_type)
        value: Any
        if isinstance(payload, dict):
            value = payload
        else:
            try:
                value = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise StructuredOutputError("invalid_json") from exc
        try:
            model = adapter.validate_python(value)
        except ValidationError as exc:
            raise StructuredOutputError("invalid_structured_output") from exc
        ensure_citation_integrity(model)
        return model


class DisabledLLMGateway:
    """Deterministic A1 placeholder used until A2+ behaviors exist."""

    def render_unavailable(self, prompt: GatewayPrompt) -> dict[str, str]:
        return {
            "mode": "deterministic_fallback",
            "reason": "llm_unavailable",
            "system_prompt_name": prompt.system_prompt,
        }


def normalize_json_payload(value: object) -> dict[str, Any] | list[Any]:
    """Parse JSON-like payloads, accepting fenced JSON strings."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        raise ValueError("LLM payload must be JSON text, dict, or list")
    text = value.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.startswith("```")]
        text = "\n".join(lines).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict | list):
        raise ValueError("LLM payload must decode to a JSON object or array")
    return parsed


class LLMGateway:
    """Compatibility wrapper exposing the simpler A1 gateway API."""

    def __init__(self, *, enabled: bool, model_name: str) -> None:
        self._enabled = enabled
        self._model_name = model_name
        self._delegate = StructuredLLMGateway()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def model_name(self) -> str:
        return self._model_name

    def ensure_enabled(self) -> None:
        if not self._enabled:
            raise LLMGatewayDisabled("LLM gateway is disabled for this environment")

    def normalize_structured_output(self, content: object) -> NormalizedLLMResponse:
        payload = normalize_json_payload(content)
        text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
        return NormalizedLLMResponse(text=text, payload=payload)


class LLMGatewayDisabled(RuntimeError):
    """Raised when a disabled gateway is used for a model-backed flow."""
