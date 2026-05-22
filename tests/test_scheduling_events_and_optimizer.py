from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app


def test_order_changes_write_scheduling_events(tmp_path, monkeypatch):
    db_path = tmp_path / "events.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    created = client.post(
        "/api/orders",
        json={
            "order_type": "normal",
            "sample_name": "事件样品",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )
    order_id = created.json()["data"]["id"]
    updated = client.patch(f"/api/orders/{order_id}", json={"order_type": "vip"})
    cancelled = client.delete(f"/api/orders/{order_id}")
    events = client.get("/api/scheduling/events")

    assert created.status_code == 201
    assert updated.status_code == 200
    assert cancelled.status_code == 200
    assert events.status_code == 200
    event_types = [item["event_type"] for item in events.json()["data"]]
    assert "order_created" in event_types
    assert "order_priority_changed" in event_types
    assert "order_cancelled" in event_types


def test_manual_scheduling_event_and_heartbeat_trigger_queue_scheduler(tmp_path, monkeypatch):
    db_path = tmp_path / "heartbeat.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    client.post(
        "/api/orders",
        json={
            "order_type": "normal",
            "sample_name": "普通样品",
            "sample_quantity": 2,
            "certification_type": "ccc",
        },
    )
    client.post(
        "/api/orders",
        json={
            "order_type": "vip",
            "sample_name": "VIP样品",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )
    manual_event = client.post(
        "/api/scheduling/events",
        json={
            "event_type": "equipment_offline",
            "severity": "medium",
            "entity_type": "equipment",
            "entity_id": "safety_tester-1",
            "payload": {"reason": "simulated failure"},
        },
    )
    heartbeat = client.post("/api/scheduling/heartbeat")
    queue = client.get("/api/queue")
    events = client.get("/api/scheduling/events", params={"status": "done"})

    assert manual_event.status_code == 201
    assert heartbeat.status_code == 200
    data = heartbeat.json()["data"]
    assert data["triggered"] is True
    assert data["schedule_run_id"]
    assert "queue_scheduler" in data["visited_agents"]
    assert queue.json()["data"]["run_id"] == data["schedule_run_id"]
    assert queue.json()["data"]["metrics"]["selected_strategy"]
    assert queue.json()["data"]["metrics"]["candidate_scores"]
    assert any(item["schedule_run_id"] == data["schedule_run_id"] for item in events.json()["data"])


def test_high_severity_event_triggers_immediate_scheduler(tmp_path, monkeypatch):
    db_path = tmp_path / "immediate.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    client.post(
        "/api/orders",
        json={
            "order_type": "vip",
            "sample_name": "立即重排样品",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )
    event = client.post(
        "/api/scheduling/events",
        json={
            "event_type": "equipment_offline",
            "severity": "high",
            "entity_type": "equipment",
            "entity_id": "safety_tester-1",
            "payload": {"reason": "critical simulated failure"},
        },
    )
    status = client.get("/api/scheduling/heartbeat/status")

    assert event.status_code == 201
    data = event.json()["data"]
    assert data["status"] == "done"
    assert data["schedule_run_id"]
    assert data["immediate_heartbeat"]["triggered"] is True
    assert status.json()["data"]["pending_event_count"] == 0


def test_heartbeat_without_pending_events_does_not_rebuild(tmp_path, monkeypatch):
    db_path = tmp_path / "no-events.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())

    heartbeat = client.post("/api/scheduling/heartbeat")
    status = client.get("/api/scheduling/heartbeat/status")

    assert heartbeat.status_code == 200
    assert heartbeat.json()["data"]["triggered"] is False
    assert heartbeat.json()["data"]["reason"] == "no_pending_events"
    assert status.status_code == 200
    assert status.json()["data"]["pending_event_count"] == 0


def test_duplicate_events_are_debounced_before_heartbeat(tmp_path, monkeypatch):
    db_path = tmp_path / "dedupe.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    payload = {
        "event_type": "consumable_shortage",
        "severity": "medium",
        "entity_type": "consumable",
        "entity_id": "emc_fixture",
        "payload": {"remaining": 0},
    }

    first = client.post("/api/scheduling/events", json=payload)
    second = client.post("/api/scheduling/events", json=payload)
    heartbeat = client.post("/api/scheduling/heartbeat")
    events = client.get("/api/scheduling/events")

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["data"]["status"] == "ignored"
    assert heartbeat.json()["data"]["processed_event_count"] == 1
    statuses = [item["status"] for item in events.json()["data"]]
    assert statuses.count("done") == 1
    assert statuses.count("ignored") == 1


def test_agent_can_run_scheduler_heartbeat_and_analyze_options(tmp_path, monkeypatch):
    db_path = tmp_path / "agent-heartbeat.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    client.post(
        "/api/orders",
        json={
            "order_type": "vip",
            "sample_name": "Agent排程样品",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )
    heartbeat = client.post("/api/agent/run", json={"task_type": "scheduler_heartbeat", "payload": {}})
    options = client.post("/api/agent/run", json={"task_type": "analyze_schedule_options", "payload": {}})

    assert heartbeat.status_code == 200
    heartbeat_data = heartbeat.json()["data"]
    assert "queue_scheduler" in heartbeat_data["visited_agents"]
    assert heartbeat_data["result"]["heartbeat"]["triggered"] is True
    assert options.status_code == 200
    option_data = options.json()["data"]
    assert "queue_scheduler" in option_data["visited_agents"]
    assert option_data["result"]["analysis"]["candidate_scores"]
