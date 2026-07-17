"""LLM JSON normalization coverage for A1."""

import pytest

from ai_service.clients.llm_gateway import LLMGateway, LLMGatewayDisabled, normalize_json_payload


def test_normalize_json_payload_accepts_fenced_json() -> None:
    payload = normalize_json_payload('```json\n{"answer":"ok"}\n```')

    assert payload == {"answer": "ok"}


def test_disabled_gateway_fails_closed() -> None:
    gateway = LLMGateway(enabled=False, model_name="disabled")

    with pytest.raises(LLMGatewayDisabled):
        gateway.ensure_enabled()
