from pathlib import Path

from rag.retriever import KnowledgeRetriever
from services.queue_service import QueueService
from services.simulation_service import SimulationService
from services.tool_client import LocalSimulationToolClient


def test_rag_retriever_returns_relevant_certification_context(tmp_path):
    retriever = KnowledgeRetriever(Path("rag/knowledge_base"), index_dir=tmp_path / "index")

    results = retriever.search("CCC 强制性认证 安全检测", top_k=2)

    assert results
    assert results[0]["score"] > 0
    assert "CCC" in results[0]["content"]


def test_local_tool_client_exposes_equipment_status_and_queue_snapshot():
    simulation = SimulationService()
    queue_service = QueueService(simulation)
    client = LocalSimulationToolClient(simulation, queue_service)

    equipment_status = client.get_equipment_status()
    queue_snapshot = client.get_queue_snapshot()

    assert "equipment" in equipment_status
    assert equipment_status["equipment"]
    assert queue_snapshot["queue_length"] == 0
    assert queue_snapshot["blocked_count"] == 0


def test_local_tool_client_can_reserve_equipment_slot():
    simulation = SimulationService()
    queue_service = QueueService(simulation)
    client = LocalSimulationToolClient(simulation, queue_service)

    reservation = client.reserve_equipment_slot(
        equipment_type="safety_tester",
        order_id="order-1",
        start_minute=0,
        duration_minutes=30,
        sample_quantity=2,
    )

    assert reservation["reserved"] is True
    assert reservation["equipment_type"] == "safety_tester"
    assert reservation["end_minute"] == 30
