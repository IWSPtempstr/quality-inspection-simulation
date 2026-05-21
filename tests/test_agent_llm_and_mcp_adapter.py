from __future__ import annotations

from fastapi.testclient import TestClient

from agents import AgentGraphRunner
from app import create_app
from config.settings import AgentModelConfig
from services.queue_service import QueueService
from services.simulation_service import SimulationService
from services.tool_client import LocalSimulationToolClient
from rag.retriever import KnowledgeRetriever
from db.session import create_tables, get_session_factory


class FailingLlmClient:
    def analyze_exception(self, *_args, **_kwargs):
        raise RuntimeError("simulated llm failure")


def test_exception_analyzer_falls_back_when_llm_fails(tmp_path):
    session_factory = get_session_factory(f"sqlite:///{tmp_path / 'llm.db'}")
    create_tables(session_factory)
    simulation = SimulationService()
    queue = QueueService(simulation)
    runner = AgentGraphRunner(
        session_factory=session_factory,
        simulation_service=simulation,
        queue_service=queue,
        retriever=KnowledgeRetriever(tmp_path / "knowledge", index_dir=tmp_path / "index"),
        tool_client=LocalSimulationToolClient(simulation, queue),
        agent_configs={
            "exception_analyzer": AgentModelConfig(
                agent_name="exception_analyzer",
                provider="openai-compatible",
                api_key="configured",
                base_url="https://example.com/v1",
                model="analysis-model",
                temperature=0.2,
                max_tokens=512,
                enable_thinking=True,
            )
        },
        llm_client=FailingLlmClient(),
    )

    result = runner.run(type("Request", (), {"task_type": "analyze_exception", "payload": {}})())

    assert result["result"]["analysis"]["mode"] == "deterministic_fallback"
    assert "simulated llm failure" in result["errors"][0]


def test_mcp_status_exposes_adapter_type(tmp_path, monkeypatch):
    db_path = tmp_path / "adapter.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MCP_ADAPTER_TYPE", "simulation")

    client = TestClient(create_app())
    response = client.get("/api/mcp/status")

    assert response.status_code == 200
    assert response.json()["data"]["adapter_type"] == "simulation"
