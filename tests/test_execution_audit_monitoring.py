from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app


def _single_step_order(sample_name: str = "执行流样品") -> dict:
    return {
        "order_type": "normal",
        "sample_name": sample_name,
        "sample_quantity": 1,
        "certification_type": "ccc",
        "detection_route": [
            {
                "project_id": "manual-safety",
                "project_type": "safety_check",
                "equipment_type": "safety_tester",
                "lab_area": "safety_lab",
                "sequence": 1,
                "duration_minutes": 30,
                "operator_requirements": {
                    "required_operator_count": 1,
                    "required_roles": ["safety_engineer"],
                    "supervision_mode": "exclusive",
                    "staff_phase": "full",
                },
            }
        ],
    }


def test_execution_status_flow_retest_audit_and_running_lock(tmp_path, monkeypatch):
    db_path = tmp_path / "execution.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    order = client.post("/api/orders", json=_single_step_order()).json()["data"]
    rebuild = client.post("/api/queue/rebuild").json()["data"]
    run_id = rebuild["run_id"]
    step = rebuild["scheduled_orders"][0]["steps"][0]

    running = client.patch(
        f"/api/schedules/steps/{step['id']}/running",
        json={"note": "开始检测"},
        headers={"X-User-Role": "operator", "X-User-Id": "operator"},
    )
    client.post("/api/orders", json=_single_step_order("后到VIP样品") | {"order_type": "vip"})
    rebuilt_with_lock = client.post("/api/queue/rebuild").json()["data"]

    completed = client.patch(
        f"/api/schedules/steps/{step['id']}/complete",
        json={"note": "检测完成"},
        headers={"X-User-Role": "operator", "X-User-Id": "operator"},
    )
    updated_order = client.get(f"/api/orders/{order['id']}").json()["data"]
    retest = client.post(f"/api/orders/{order['id']}/retest", json={"reason": "复核不一致"}).json()["data"]
    audit = client.get("/api/admin/audit-logs").json()["data"]

    assert running.status_code == 200
    locked_order = next(item for item in rebuilt_with_lock["scheduled_orders"] if item["id"] == order["id"])
    assert locked_order["status"] == "running"
    assert any(item.get("locked") for item in locked_order["steps"])
    assert completed.status_code == 200
    assert updated_order["status"] == "completed"
    assert retest["parent_order_id"] == order["id"]
    assert retest["retest_reason"] == "复核不一致"
    actions = {item["action"] for item in audit}
    assert {"step_started", "step_completed", "retest_created"}.issubset(actions)
    gantt = client.get(f"/api/schedules/{run_id}/gantt").json()["data"]
    assert gantt["bars"]


def test_monitor_report_users_and_permission_guard(tmp_path, monkeypatch):
    db_path = tmp_path / "monitor.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    users = client.get("/api/admin/users").json()["data"]
    report = client.get("/api/monitor/report").json()["data"]
    forbidden = client.post(
        "/api/scheduling/events",
        json={
            "event_type": "equipment_offline",
            "severity": "medium",
            "entity_type": "equipment",
            "entity_id": "safety_tester-1",
        },
        headers={"X-User-Role": "viewer", "X-User-Id": "viewer"},
    )

    assert {item["role"] for item in users} >= {"admin", "scheduler", "operator"}
    assert {item["dataset"] for item in report["dataset_reports"]} == {
        "scenario_synthetic_center",
        "scenario_synthetic_center_large",
    }
    assert forbidden.status_code == 403
