from __future__ import annotations

from config.settings import get_settings


def test_settings_loads_api_configuration_from_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_API_KEY=llm-key-from-file",
                "LLM_BASE_URL=https://llm.example.com/v1",
                "LLM_MODEL=test-chat-model",
                "EMBEDDING_PROVIDER=openai-compatible",
                "EMBEDDING_API_KEY=embedding-key-from-file",
                "EMBEDDING_BASE_URL=https://embedding.example.com/v1",
                "EMBEDDING_MODEL=test-embedding-model",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

    settings = get_settings()

    assert settings.llm_api_key == "llm-key-from-file"
    assert settings.llm_base_url == "https://llm.example.com/v1"
    assert settings.llm_model == "test-chat-model"
    assert settings.embedding_api_key == "embedding-key-from-file"
    assert settings.embedding_base_url == "https://embedding.example.com/v1"
    assert settings.embedding_model == "test-embedding-model"


def test_process_environment_overrides_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("EMBEDDING_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.setenv("EMBEDDING_API_KEY", "from-process")

    settings = get_settings()

    assert settings.embedding_api_key == "from-process"


def test_settings_supports_agent_specific_llm_configuration(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=openai-compatible",
                "LLM_API_KEY=global-key",
                "LLM_BASE_URL=https://global.example.com/v1",
                "LLM_MODEL=global-model",
                "LLM_TEMPERATURE=0.1",
                "LLM_MAX_TOKENS=512",
                "LLM_ENABLE_THINKING=false",
                "AGENT_ORCHESTRATOR_MODEL=router-model",
                "AGENT_ORCHESTRATOR_MAX_TOKENS=128",
                "AGENT_ORDER_MANAGER_MODEL=",
                "AGENT_EXCEPTION_ANALYZER_MODEL=deep-analysis-model",
                "AGENT_EXCEPTION_ANALYZER_TEMPERATURE=0.3",
                "AGENT_EXCEPTION_ANALYZER_MAX_TOKENS=2048",
                "AGENT_EXCEPTION_ANALYZER_ENABLE_THINKING=true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ENV_FILE", str(env_file))
    for key in [
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_TEMPERATURE",
        "LLM_MAX_TOKENS",
        "LLM_ENABLE_THINKING",
        "AGENT_ORCHESTRATOR_MODEL",
        "AGENT_ORCHESTRATOR_MAX_TOKENS",
        "AGENT_ORDER_MANAGER_MODEL",
        "AGENT_ORDER_MANAGER_TEMPERATURE",
        "AGENT_ORDER_MANAGER_MAX_TOKENS",
        "AGENT_ORDER_MANAGER_ENABLE_THINKING",
        "AGENT_PROJECT_IDENTIFIER_MODEL",
        "AGENT_PROJECT_IDENTIFIER_TEMPERATURE",
        "AGENT_PROJECT_IDENTIFIER_MAX_TOKENS",
        "AGENT_PROJECT_IDENTIFIER_ENABLE_THINKING",
        "AGENT_RAG_RETRIEVER_MODEL",
        "AGENT_RAG_RETRIEVER_TEMPERATURE",
        "AGENT_RAG_RETRIEVER_MAX_TOKENS",
        "AGENT_RAG_RETRIEVER_ENABLE_THINKING",
        "AGENT_QUEUE_SCHEDULER_MODEL",
        "AGENT_QUEUE_SCHEDULER_TEMPERATURE",
        "AGENT_QUEUE_SCHEDULER_MAX_TOKENS",
        "AGENT_QUEUE_SCHEDULER_ENABLE_THINKING",
        "AGENT_EQUIPMENT_MONITOR_MODEL",
        "AGENT_EQUIPMENT_MONITOR_TEMPERATURE",
        "AGENT_EQUIPMENT_MONITOR_MAX_TOKENS",
        "AGENT_EQUIPMENT_MONITOR_ENABLE_THINKING",
        "AGENT_EXCEPTION_ANALYZER_MODEL",
        "AGENT_EXCEPTION_ANALYZER_TEMPERATURE",
        "AGENT_EXCEPTION_ANALYZER_MAX_TOKENS",
        "AGENT_EXCEPTION_ANALYZER_ENABLE_THINKING",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = get_settings()

    orchestrator = settings.agent_configs["orchestrator"]
    order_manager = settings.agent_configs["order_manager"]
    exception_analyzer = settings.agent_configs["exception_analyzer"]

    assert orchestrator.model == "router-model"
    assert orchestrator.max_tokens == 128
    assert orchestrator.enable_thinking is False
    assert order_manager.model == "global-model"
    assert order_manager.api_key == "global-key"
    assert exception_analyzer.model == "deep-analysis-model"
    assert exception_analyzer.temperature == 0.3
    assert exception_analyzer.max_tokens == 2048
    assert exception_analyzer.enable_thinking is True
    assert exception_analyzer.public_dict()["api_key_configured"] is True
    assert "api_key" not in exception_analyzer.public_dict()
