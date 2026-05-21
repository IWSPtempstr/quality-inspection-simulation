from fastapi.testclient import TestClient

from app import create_app
from services.mcp_client import McpToolClient
from services.queue_service import QueueService
from services.simulation_service import SimulationService
from services.tool_client import LocalSimulationToolClient


def test_mcp_client_reports_fallback_status_when_stdio_command_fails():
    simulation = SimulationService()
    queue = QueueService(simulation)
    fallback = LocalSimulationToolClient(simulation, queue)
    client = McpToolClient(command="missing-mcp-command", args=[], fallback_client=fallback)

    status = client.status()
    equipment = client.get_equipment_status()

    assert status["mode"] == "fallback"
    assert status["available"] is False
    assert equipment["equipment"]


def test_mcp_status_api_exposes_tool_mode(tmp_path, monkeypatch):
    db_path = tmp_path / "mcp.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MCP_SERVER_COMMAND", "missing-mcp-command")

    client = TestClient(create_app())
    response = client.get("/api/mcp/status")

    assert response.status_code == 200
    assert response.json()["data"]["mode"] == "fallback"


def test_mcp_queue_snapshot_uses_application_schedule_state(tmp_path, monkeypatch):
    db_path = tmp_path / "mcp-shared.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    app = create_app()
    client = TestClient(app)
    create_response = client.post(
        "/api/orders",
        json={
            "order_type": "vip",
            "sample_name": "共享状态样品",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )
    rebuild_response = client.post("/api/queue/rebuild")

    snapshot = app.state.tool_client.get_queue_snapshot()

    assert create_response.status_code == 201
    assert rebuild_response.status_code == 200
    assert snapshot["queue_length"] == 1
    assert snapshot["scheduled_orders"][0]["sample_name"] == "共享状态样品"


def test_jinja_management_pages_render(tmp_path, monkeypatch):
    db_path = tmp_path / "web.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())

    for path, marker in [
        ("/", "检测队列仪表盘"),
        ("/orders", "订单管理"),
        ("/queue", "队列与排程"),
        ("/knowledge", "知识库检索"),
        ("/agents", "Agent 执行轨迹"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert marker in response.text
