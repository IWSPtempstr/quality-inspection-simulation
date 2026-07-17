"""Typed settings coverage for A1."""

import pytest

from ai_service.conf.settings import AIServiceSettings


def test_production_requires_service_token() -> None:
    with pytest.raises(ValueError, match="AI_SERVICE_SERVICE_BEARER_TOKEN"):
        AIServiceSettings(environment="production")


def test_development_allows_missing_service_token() -> None:
    settings = AIServiceSettings(environment="development")

    assert settings.default_model == "disabled"
