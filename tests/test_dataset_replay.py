from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app import create_app


def _client(tmp_path, monkeypatch, name: str = "dataset-replay") -> TestClient:
    db_path = tmp_path / f"{name}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SCHEDULER_HEARTBEAT_ENABLED", "false")
    return TestClient(create_app())


def test_dataset_list_and_summary_include_available_scenarios(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "dataset-list")

    listed = client.get("/api/datasets", headers={"X-User-Role": "viewer"})
    summary = client.get("/api/datasets/scenario_synthetic_center/summary", headers={"X-User-Role": "viewer"})

    assert listed.status_code == 200
    names = {item["name"] for item in listed.json()["data"]["items"]}
    assert names >= {
        "mechanism_validation",
        "scenario_synthetic_center",
        "scenario_synthetic_center_large",
    }
    assert summary.status_code == 200
    data = summary.json()["data"]
    assert data["order_count"] == 500
    assert data["start_time"] < data["end_time"]
    assert sum(data["order_type_distribution"].values()) == 500
    assert sum(data["certification_distribution"].values()) == 500


def test_replay_start_resets_runtime_and_defers_order_import(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "replay-start")
    existing = client.post(
        "/api/orders",
        json={
            "order_type": "vip",
            "sample_name": "启动前订单",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )

    started = client.post(
        "/api/datasets/scenario_synthetic_center/replay/start",
        json={"speed_minutes_per_second": 30, "max_orders": 8, "reset_runtime": True},
    )
    orders = client.get("/api/orders")

    assert existing.status_code == 201
    assert started.status_code == 201
    data = started.json()["data"]
    assert data["status"] == "created"
    assert data["total_orders"] == 8
    assert data["imported_orders"] == 0
    assert data["current_simulation_time"] == data["start_time"]
    assert orders.json()["data"]["total"] == 0


def test_replay_tick_imports_arrived_orders_and_triggers_scheduler(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "replay-tick")
    run = client.post(
        "/api/datasets/scenario_synthetic_center/replay/start",
        json={"speed_minutes_per_second": 30, "max_orders": 12},
    ).json()["data"]

    ticked = client.post(f"/api/datasets/replay/{run['id']}/tick")
    detail = client.get(f"/api/datasets/replay/{run['id']}").json()["data"]
    orders = client.get("/api/orders").json()["data"]["items"]
    queue = client.get("/api/queue").json()["data"]

    assert ticked.status_code == 200
    assert detail["status"] in {"running", "completed"}
    assert detail["imported_orders"] > 0
    assert len(orders) == detail["imported_orders"]
    current_time = datetime.fromisoformat(detail["current_simulation_time"])
    assert all(datetime.fromisoformat(order["arrival_time"]) <= current_time for order in orders)
    assert detail["latest_schedule_run_id"]
    assert queue["run_id"] == detail["latest_schedule_run_id"]


def test_replay_step_imports_one_order_and_pause_blocks_tick(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "replay-step")
    run = client.post(
        "/api/datasets/scenario_synthetic_center/replay/start",
        json={"speed_minutes_per_second": 30, "max_orders": 5},
    ).json()["data"]

    first = client.post(f"/api/datasets/replay/{run['id']}/step").json()["data"]
    paused = client.post(f"/api/datasets/replay/{run['id']}/pause").json()["data"]
    ticked_while_paused = client.post(f"/api/datasets/replay/{run['id']}/tick").json()["data"]
    resumed = client.post(f"/api/datasets/replay/{run['id']}/resume").json()["data"]
    second = client.post(f"/api/datasets/replay/{run['id']}/step").json()["data"]

    assert first["imported_orders"] == 1
    assert first["latest_order_id"]
    assert paused["status"] == "paused"
    assert ticked_while_paused["status"] == "paused"
    assert ticked_while_paused["imported_orders"] == 1
    assert ticked_while_paused["current_simulation_time"] == paused["current_simulation_time"]
    assert resumed["status"] == "running"
    assert second["imported_orders"] == 2


def test_dataset_replay_permissions_errors_stream_and_dashboard_controls(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "replay-ui")

    invalid = client.get("/api/datasets/missing_dataset/summary")
    forbidden_start = client.post(
        "/api/datasets/scenario_synthetic_center/replay/start",
        json={"max_orders": 1},
        headers={"X-User-Role": "viewer"},
    )
    started = client.post(
        "/api/datasets/scenario_synthetic_center/replay/start",
        json={"max_orders": 1},
    ).json()["data"]
    stream = client.get(f"/api/datasets/replay/{started['id']}/stream")
    dashboard = client.get("/")

    assert invalid.status_code == 404
    assert forbidden_start.status_code == 403
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "dataset-replay-console" in dashboard.text
    assert "数据集回放控制台" in dashboard.text
