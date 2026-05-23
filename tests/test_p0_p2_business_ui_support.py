from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app


def _client(tmp_path, monkeypatch, name: str = "business-ui") -> TestClient:
    db_path = tmp_path / f"{name}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    return TestClient(create_app())


def test_orders_list_filters_pagination_and_permissions(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "orders-list")
    normal = client.post(
        "/api/orders",
        json={
            "order_type": "normal",
            "sample_name": "普通照明电器",
            "sample_quantity": 2,
            "certification_type": "ccc",
        },
    ).json()["data"]
    urgent = client.post(
        "/api/orders",
        json={
            "order_type": "urgent",
            "sample_name": "加急电器附件",
            "sample_quantity": 1,
            "certification_type": "cvc",
        },
    ).json()["data"]
    client.delete(f"/api/orders/{normal['id']}")

    visible = client.get(
        "/api/orders",
        params={"q": "加急", "order_type": "urgent", "limit": 10, "offset": 0},
        headers={"X-User-Role": "viewer", "X-User-Id": "viewer"},
    )
    hidden_cancelled = client.get("/api/orders")
    with_cancelled = client.get("/api/orders", params={"include_cancelled": "true"})
    forbidden_write = client.post(
        "/api/orders",
        json={
            "order_type": "normal",
            "sample_name": "无权创建样品",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
        headers={"X-User-Role": "viewer", "X-User-Id": "viewer"},
    )

    assert visible.status_code == 200
    assert visible.json()["data"]["total"] == 1
    assert visible.json()["data"]["items"][0]["id"] == urgent["id"]
    assert hidden_cancelled.json()["data"]["total"] == 1
    assert with_cancelled.json()["data"]["total"] == 2
    assert forbidden_write.status_code == 403


def test_read_permissions_and_agent_task_permissions_are_enforced(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "permissions")
    order = client.post(
        "/api/orders",
        json={
            "order_type": "vip",
            "sample_name": "权限测试样品",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    ).json()["data"]
    client.post("/api/queue/rebuild")

    viewer_order = client.get(
        f"/api/orders/{order['id']}",
        headers={"X-User-Role": "viewer", "X-User-Id": "viewer"},
    )
    viewer_queue = client.get(
        "/api/queue",
        headers={"X-User-Role": "viewer", "X-User-Id": "viewer"},
    )
    operator_queue = client.get(
        "/api/queue",
        headers={"X-User-Role": "operator", "X-User-Id": "operator"},
    )
    operator_stream = client.get(
        "/api/notifications/stream",
        headers={"X-User-Role": "operator", "X-User-Id": "operator"},
    )
    viewer_stream = client.get(
        "/api/notifications/stream",
        headers={"X-User-Role": "viewer", "X-User-Id": "viewer"},
    )
    viewer_agent_query = client.post(
        "/api/agent/run",
        json={"task_type": "query_queue", "payload": {}},
        headers={"X-User-Role": "viewer", "X-User-Id": "viewer"},
    )
    viewer_agent_rebuild = client.post(
        "/api/agent/run",
        json={"task_type": "rebuild_queue", "payload": {}},
        headers={"X-User-Role": "viewer", "X-User-Id": "viewer"},
    )
    audit = client.get("/api/admin/audit-logs").json()["data"]

    assert viewer_order.status_code == 200
    assert viewer_queue.status_code == 200
    assert operator_queue.status_code == 403
    assert operator_stream.status_code == 200
    assert viewer_stream.status_code == 403
    assert viewer_agent_query.status_code == 200
    assert viewer_agent_rebuild.status_code == 403
    assert any(item["action"] == "agent_run" for item in audit)


def test_business_pages_expose_accessible_operational_surfaces(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "pages")

    dashboard = client.get("/")
    orders = client.get("/orders")
    queue = client.get("/queue")
    notifications = client.get("/notifications")

    for response in [dashboard, orders, queue, notifications]:
        assert response.status_code == 200
        assert 'href="#main-content"' in response.text
        assert 'aria-live="polite"' in response.text

    assert "订单列表" in orders.text
    assert "orders-table" in orders.text
    assert "排程步骤" in queue.text
    assert "strategy-table" in queue.text
    assert "通知收件箱" in notifications.text
    assert "sse-status" in notifications.text
    assert "待处理事件" in dashboard.text
    assert "<pre id=\"event-report\"" not in dashboard.text


def test_monitor_report_caches_dataset_summary_but_keeps_events_live(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "monitor-cache")
    service = client.app.state.monitoring_report_service

    first = client.get("/api/monitor/report").json()["data"]
    second = client.get("/api/monitor/report").json()["data"]
    client.post(
        "/api/scheduling/events",
        json={
            "event_type": "equipment_offline",
            "severity": "medium",
            "entity_type": "equipment",
            "entity_id": "safety_tester-1",
        },
    )
    third = client.get("/api/monitor/report").json()["data"]

    assert first["dataset_reports"] == second["dataset_reports"]
    assert service.cache_stats()["dataset_hits"] >= 1
    assert third["event_summary"]["total"] == second["event_summary"]["total"] + 1
