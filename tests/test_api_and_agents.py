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
    assert "orchestrator" in data["agent_configs"]


def test_agent_run_with_session_id_uses_structured_summary_context(tmp_path, monkeypatch):
    db_path = tmp_path / "agent-session.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SCHEDULER_HEARTBEAT_ENABLED", "false")

    client = TestClient(create_app())

    first = client.post(
        "/api/agent/run",
        json={
            "task_type": "draft_order_from_text",
            "session_id": "session-demo",
            "payload": {"user_text": "为温控开关创建VIP CCC检测订单，200个样品"},
        },
    )
    second = client.post(
        "/api/agent/run",
        json={
            "task_type": "route_user_query",
            "session_id": "session-demo",
            "payload": {"user_query": "继续看这个订单草稿"},
        },
    )
    session_detail = client.get("/api/agent/sessions/session-demo")

    assert first.status_code == 200
    assert first.json()["data"]["session_id"] == "session-demo"
    assert first.json()["data"]["session_context_used"] is False
    assert second.status_code == 200
    second_data = second.json()["data"]
    assert second_data["session_id"] == "session-demo"
    assert second_data["session_context_used"] is True
    assert second_data["session_context"]["last_task_type"] == "draft_order_from_text"
    assert "order_draft" in second_data["session_context"]["summary"]
    assert session_detail.status_code == 200
    assert session_detail.json()["data"]["last_task_type"] == "route_user_query"


def test_agent_session_can_be_closed_and_no_longer_used(tmp_path, monkeypatch):
    db_path = tmp_path / "agent-session-close.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SCHEDULER_HEARTBEAT_ENABLED", "false")

    client = TestClient(create_app())

    client.post(
        "/api/agent/run",
        json={"task_type": "query_queue", "session_id": "session-close", "payload": {}},
    )
    close_response = client.delete("/api/agent/sessions/session-close")
    second = client.post(
        "/api/agent/run",
        json={"task_type": "query_queue", "session_id": "session-close", "payload": {}},
    )

    assert close_response.status_code == 200
    assert close_response.json()["data"]["status"] == "closed"
    assert second.status_code == 200
    assert second.json()["data"]["session_context_used"] is False


def test_agent_configs_endpoint_returns_sanitized_per_agent_config(tmp_path, monkeypatch):
    db_path = tmp_path / "agent-configs.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("LLM_API_KEY", "secret-key")
    monkeypatch.setenv("AGENT_QUEUE_SCHEDULER_MODEL", "queue-model")
    monkeypatch.setenv("AGENT_EXCEPTION_ANALYZER_ENABLE_THINKING", "true")

    client = TestClient(create_app())

    response = client.get("/api/agent/configs")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["queue_scheduler"]["model"] == "queue-model"
    assert data["queue_scheduler"]["api_key_configured"] is True
    assert data["exception_analyzer"]["enable_thinking"] is True
    assert "api_key" not in data["queue_scheduler"]
