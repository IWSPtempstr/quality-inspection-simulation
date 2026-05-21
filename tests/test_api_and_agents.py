from fastapi.testclient import TestClient

from app import create_app


def test_order_api_and_queue_rebuild_prioritize_vip_orders(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())

    normal_response = client.post(
        "/api/orders",
        json={
            "order_type": "normal",
            "sample_name": "普通电器附件",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )
    vip_response = client.post(
        "/api/orders",
        json={
            "order_type": "vip",
            "sample_name": "VIP家用电器",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )

    assert normal_response.status_code == 201
    assert vip_response.status_code == 201

    rebuild_response = client.post("/api/queue/rebuild")

    assert rebuild_response.status_code == 200
    scheduled = rebuild_response.json()["data"]["scheduled_orders"]
    assert scheduled[0]["order_type"] == "vip"


def test_agent_run_can_query_queue_and_report_direct_handoff(tmp_path, monkeypatch):
    db_path = tmp_path / "agent.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())

    response = client.post(
        "/api/agent/run",
        json={"task_type": "query_queue", "payload": {}},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["task_type"] == "query_queue"
    assert "orchestrator" in data["visited_agents"]
    assert "queue_scheduler" in data["visited_agents"]
    assert "equipment_monitor" in data["visited_agents"]
    assert data["handoffs"]
