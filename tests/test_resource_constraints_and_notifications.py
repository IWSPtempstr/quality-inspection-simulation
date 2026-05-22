from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import create_app
from domain.schemas import CertificationType, OrderType, QueueStatus
from services.queue_service import QueueService
from services.simulation_service import SimulationService


TZ = timezone(timedelta(hours=8))


def _route_step(project_id: str, equipment_type: str, lab_area: str, sequence: int, duration: int = 30) -> dict:
    return {
        "project_id": project_id,
        "project_type": "safety_check",
        "equipment_type": equipment_type,
        "lab_area": lab_area,
        "sequence": sequence,
        "duration_minutes": duration,
        "setup_minutes": 5,
        "duration_profile": {"t_min": duration, "t_mode": duration, "t_max": duration},
        "staff_role": "safety_engineer",
        "operator_requirements": {
            "required_operator_count": 1,
            "required_roles": ["safety_engineer"],
            "supervision_mode": "shared_supervision",
            "staff_phase": "running",
        },
        "consumable_type": "safety_probe",
        "consumable_units_per_batch": 1,
    }


def _order(order_id: str, route: list[dict], arrival: datetime | None = None) -> dict:
    arrival = arrival or datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    return {
        "id": order_id,
        "order_type": OrderType.NORMAL,
        "sample_name": f"{order_id}样品",
        "sample_quantity": 1,
        "certification_type": CertificationType.CCC,
        "requested_projects": [],
        "detection_route": route,
        "preprocessing_profile": {
            "required_minutes": 15,
            "lab_area": "intake",
            "required_roles": ["sample_operator"],
            "resource_type": "prep_station",
        },
        "status": QueueStatus.PENDING,
        "arrival_time": arrival,
        "promised_finish_time": arrival + timedelta(days=2),
        "created_at": arrival,
        "updated_at": arrival,
    }


def test_scheduler_inserts_preprocessing_transfer_and_respects_employee_instances():
    operations = {
        "employees": [
            {
                "employee_id": "emp-safety-1",
                "name": "安全工程师1",
                "roles": ["safety_engineer"],
                "skills": ["safety_check", "safety_tester"],
                "lab_areas": ["safety_lab", "emc_lab"],
                "shift_id": "lab_day",
                "max_parallel_assignments": 1,
            },
            {
                "employee_id": "emp-prep-1",
                "name": "样品前处理员1",
                "roles": ["sample_operator"],
                "skills": ["preprocessing"],
                "lab_areas": ["intake"],
                "shift_id": "lab_day",
                "max_parallel_assignments": 1,
            },
            {
                "employee_id": "emp-transfer-1",
                "name": "转运员1",
                "roles": ["transfer_operator"],
                "skills": ["sample_transfer"],
                "lab_areas": ["safety_lab", "emc_lab"],
                "shift_id": "lab_day",
                "max_parallel_assignments": 1,
            },
        ],
        "transfer_resources": [{"resource_id": "cart-1", "resource_type": "transfer_cart"}],
        "transfer_matrix": {
            "safety_lab->emc_lab": {
                "duration_minutes": 10,
                "required_roles": ["transfer_operator"],
                "resource_type": "transfer_cart",
            }
        },
        "preprocessing_resources": [{"resource_id": "prep-1", "resource_type": "prep_station"}],
        "consumables": {"safety_probe": {"daily_capacity": 20}},
    }
    route = [
        _route_step("safety-a", "safety_tester", "safety_lab", 1, duration=30),
        _route_step("safety-b", "safety_tester", "emc_lab", 2, duration=30),
    ]

    schedule = QueueService(SimulationService(operations_constraints=operations)).rebuild_schedule(
        [
            _order("order-a", route),
            _order("order-b", [_route_step("safety-c", "safety_tester", "safety_lab", 1, duration=30)]),
        ]
    )

    first_order = next(order for order in schedule["scheduled_orders"] if order["id"] == "order-a")
    second_order = next(order for order in schedule["scheduled_orders"] if order["id"] == "order-b")
    kinds = [step["step_kind"] for step in first_order["steps"]]

    assert kinds == ["preprocessing", "detection", "transfer", "detection"]
    assert first_order["steps"][0]["assigned_employee_ids"] == ["emp-prep-1"]
    assert first_order["steps"][2]["resource_ids"] == ["cart-1"]
    assert first_order["steps"][1]["setup_minutes"] == 5
    assert first_order["steps"][1]["duration_minutes"] == 35
    assert second_order["steps"][1]["start_time"] >= first_order["steps"][1]["end_time"]


def test_notification_agent_clock_api_and_sse_stream(tmp_path, monkeypatch):
    db_path = tmp_path / "notifications.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    create_response = client.post(
        "/api/orders",
        json={
            "order_type": "vip",
            "sample_name": "通知样品",
            "sample_quantity": 1,
            "certification_type": "ccc",
        },
    )
    rebuild_response = client.post("/api/queue/rebuild")
    pending_response = client.get("/api/notifications", params={"status": "pending"})
    agent_response = client.post("/api/agent/run", json={"task_type": "query_notifications", "payload": {}})

    assert create_response.status_code == 201
    assert rebuild_response.status_code == 200
    assert pending_response.status_code == 200
    assert pending_response.json()["data"]
    assert "notification_agent" in agent_response.json()["data"]["visited_agents"]

    first_planned = pending_response.json()["data"][0]["planned_trigger_time"]
    advance_response = client.post("/api/simulation/clock/advance", json={"current_time": first_planned})
    triggered_response = client.get("/api/notifications", params={"status": "triggered"})

    assert advance_response.status_code == 200
    assert triggered_response.status_code == 200
    assert triggered_response.json()["data"]

    with client.stream("GET", "/api/notifications/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        first_line = next(line for line in response.iter_lines() if line.startswith("data:"))
        assert "notification_type" in first_line

    notification_id = triggered_response.json()["data"][0]["id"]
    read_response = client.patch(f"/api/notifications/{notification_id}/read")

    assert read_response.status_code == 200
    assert read_response.json()["data"]["status"] == "read"
