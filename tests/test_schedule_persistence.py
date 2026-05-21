from fastapi.testclient import TestClient

from app import create_app


def test_queue_rebuild_persists_schedule_run_and_steps(tmp_path, monkeypatch):
    db_path = tmp_path / "schedule.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    for order_type in ["normal", "urgent", "vip"]:
        response = client.post(
            "/api/orders",
            json={
                "order_type": order_type,
                "sample_name": f"{order_type}样品",
                "sample_quantity": 2,
                "certification_type": "ccc",
            },
        )
        assert response.status_code == 201

    rebuild = client.post("/api/queue/rebuild")
    schedules = client.get("/api/schedules")

    assert rebuild.status_code == 200
    run_id = rebuild.json()["data"]["run_id"]
    assert run_id
    assert schedules.status_code == 200
    assert schedules.json()["data"][0]["id"] == run_id

    detail = client.get(f"/api/schedules/{run_id}")

    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["id"] == run_id
    assert data["scheduled_count"] == 3
    assert data["steps"]
    assert data["steps"][0]["order_type"] == "vip"


def test_queue_endpoint_returns_latest_persisted_schedule(tmp_path, monkeypatch):
    db_path = tmp_path / "latest.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    client.post(
        "/api/orders",
        json={
            "order_type": "vip",
            "sample_name": "VIP样品",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )
    run_id = client.post("/api/queue/rebuild").json()["data"]["run_id"]

    queue = client.get("/api/queue")

    assert queue.status_code == 200
    assert queue.json()["data"]["run_id"] == run_id
    assert queue.json()["data"]["scheduled_orders"][0]["order_type"] == "vip"

