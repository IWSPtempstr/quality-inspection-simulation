from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_secrets(monkeypatch, tmp_path):
    """Keep tests on deterministic local providers unless a test opts in."""
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    for name in [
        "LLM_API_KEY",
        "EMBEDDING_API_KEY",
        "AGENT_ORCHESTRATOR_API_KEY",
        "AGENT_ORDER_MANAGER_API_KEY",
        "AGENT_PROJECT_IDENTIFIER_API_KEY",
        "AGENT_RAG_RETRIEVER_API_KEY",
        "AGENT_QUEUE_SCHEDULER_API_KEY",
        "AGENT_EQUIPMENT_MONITOR_API_KEY",
        "AGENT_EXCEPTION_ANALYZER_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RAG_INDEX_DIR", str(Path(tmp_path) / "rag_index"))
