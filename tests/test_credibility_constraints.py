from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from domain.schemas import CertificationType, OrderType, QueueStatus
from scripts.generate_synthetic_center_dataset import generate_dataset
from services.queue_service import QueueService
from services.simulation_service import SimulationService


TZ = timezone(timedelta(hours=8))


def _base_order(order_id: str, arrival: datetime) -> dict:
    return {
        "id": order_id,
        "order_type": OrderType.NORMAL,
        "sample_name": f"{order_id}样品",
        "sample_quantity": 1,
        "certification_type": CertificationType.CVC,
        "requested_projects": [],
        "status": QueueStatus.PENDING,
        "arrival_time": arrival,
        "promised_finish_time": arrival + timedelta(days=10),
        "created_at": arrival,
        "updated_at": arrival,
    }


def _environment_step(project_id: str, sequence: int = 1, duration_minutes: int = 2880) -> dict:
    return {
        "project_id": project_id,
        "project_type": "environmental_check",
        "equipment_type": "environmental_chamber",
        "lab_area": "environmental_lab",
        "sequence": sequence,
        "duration_minutes": duration_minutes,
        "setup_minutes": 30,
        "continuous_operation": True,
        "can_cross_workday": True,
        "operator_requirements": {
            "required_operator_count": 1,
            "required_roles": ["environmental_engineer"],
            "supervision_mode": "setup_only",
            "staff_phase": "setup_unload",
        },
    }


def test_continuous_environmental_detection_crosses_days_and_keeps_equipment_exclusive():
    arrival = datetime(2026, 6, 1, 16, 0, tzinfo=TZ)
    first = _base_order("env-long-a", arrival)
    second = _base_order("env-long-b", arrival)
    first["detection_route"] = [_environment_step("env-a")]
    second["detection_route"] = [_environment_step("env-b")]
    simulation = SimulationService(
        equipment_catalog={
            "equipment_types": [
                {
                    "equipment_type": "environmental_chamber",
                    "d": 1,
                    "capacity_n": 1,
                    "lab_area": "environmental_lab",
                    "supported_project_types": ["environmental_check"],
                    "instances": [
                        {
                            "equipment_id": "environmental_chamber-1",
                            "equipment_type": "environmental_chamber",
                            "status": "idle",
                            "capacity_n": 1,
                            "lab_area": "environmental_lab",
                        }
                    ],
                }
            ]
        },
        operations_constraints={
            "employees": [
                {
                    "employee_id": "emp-env-1",
                    "name": "环境工程师1",
                    "roles": ["environmental_engineer"],
                    "skills": ["environmental_check", "environmental_chamber"],
                    "lab_areas": ["environmental_lab"],
                    "shift_id": "environment_day",
                    "max_parallel_assignments": 3,
                }
            ],
            "shifts": [{"shift_id": "environment_day", "start": "09:00", "end": "18:00"}],
            "preprocessing_resources": [],
            "transfer_resources": [],
            "transfer_matrix": {},
            "consumables": {},
            "maintenance_windows": [],
            "failure_events": [],
        },
    )

    schedule = QueueService(simulation).rebuild_schedule([first, second])

    by_id = {order["id"]: order for order in schedule["scheduled_orders"]}
    first_step = by_id["env-long-a"]["steps"][0]
    second_step = by_id["env-long-b"]["steps"][0]
    assert first_step["start_time"] == "2026-06-01T16:00:00+08:00"
    assert first_step["end_time"] == "2026-06-03T16:00:00+08:00"
    assert second_step["start_time"] >= first_step["end_time"]
    assert first_step["staff_end_time"] < first_step["end_time"]
    assert schedule["metrics"]["continuous_step_count"] == 2


def test_employee_shift_and_unavailable_windows_block_staff_assignment():
    arrival = datetime(2026, 6, 1, 15, 0, tzinfo=TZ)
    order = _base_order("shifted", arrival)
    order["detection_route"] = [
        {
            "project_id": "safety-shift",
            "project_type": "safety_check",
            "equipment_type": "safety_tester",
            "lab_area": "safety_lab",
            "sequence": 1,
            "duration_minutes": 60,
            "operator_requirements": {
                "required_operator_count": 1,
                "required_roles": ["safety_engineer"],
                "supervision_mode": "exclusive",
                "staff_phase": "running",
            },
        }
    ]
    simulation = SimulationService(
        equipment_catalog={
            "equipment_types": [
                {
                    "equipment_type": "safety_tester",
                    "d": 1,
                    "capacity_n": 1,
                    "lab_area": "safety_lab",
                    "supported_project_types": ["safety_check"],
                    "instances": [
                        {
                            "equipment_id": "safety_tester-1",
                            "equipment_type": "safety_tester",
                            "status": "idle",
                            "capacity_n": 1,
                            "lab_area": "safety_lab",
                        }
                    ],
                }
            ]
        },
        operations_constraints={
            "employees": [
                {
                    "employee_id": "emp-safety-1",
                    "name": "安全工程师1",
                    "roles": ["safety_engineer"],
                    "skills": ["safety_check", "safety_tester"],
                    "lab_areas": ["safety_lab"],
                    "shift_id": "morning",
                    "max_parallel_assignments": 1,
                    "unavailable_windows": [
                        {
                            "start": "2026-06-02T09:00:00+08:00",
                            "end": "2026-06-02T12:00:00+08:00",
                            "reason": "training",
                        }
                    ],
                }
            ],
            "shifts": [{"shift_id": "morning", "start": "09:00", "end": "12:00"}],
            "preprocessing_resources": [],
            "transfer_resources": [],
            "transfer_matrix": {},
            "consumables": {},
            "maintenance_windows": [],
            "failure_events": [],
        },
    )

    schedule = QueueService(simulation).rebuild_schedule([order])

    step = schedule["scheduled_orders"][0]["steps"][0]
    assert step["start_time"] == "2026-06-03T09:00:00+08:00"
    assert step["assigned_employee_ids"] == ["emp-safety-1"]
    assert schedule["metrics"]["shift_violation_count"] == 0


def test_equipment_performance_factor_changes_duration_and_selected_instance():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    order = _base_order("heterogeneous", arrival)
    order["detection_route"] = [
        {
            "project_id": "heterogeneous-safety",
            "project_type": "safety_check",
            "equipment_type": "safety_tester",
            "lab_area": "safety_lab",
            "sequence": 1,
            "duration_minutes": 100,
            "operator_requirements": {
                "required_operator_count": 1,
                "required_roles": ["safety_engineer"],
                "supervision_mode": "shared_supervision",
                "staff_phase": "running",
            },
        }
    ]
    simulation = SimulationService(
        equipment_catalog={
            "equipment_types": [
                {
                    "equipment_type": "safety_tester",
                    "d": 2,
                    "capacity_n": 1,
                    "lab_area": "safety_lab",
                    "supported_project_types": ["safety_check"],
                    "instances": [
                        {
                            "equipment_id": "safety_tester-slow",
                            "equipment_type": "safety_tester",
                            "status": "idle",
                            "capacity_n": 1,
                            "lab_area": "safety_lab",
                            "performance_factor": 1.4,
                        },
                        {
                            "equipment_id": "safety_tester-fast",
                            "equipment_type": "safety_tester",
                            "status": "idle",
                            "capacity_n": 1,
                            "lab_area": "safety_lab",
                            "performance_factor": 0.75,
                        },
                    ],
                }
            ]
        },
        operations_constraints={
            "employees": [
                {
                    "employee_id": "emp-safety-1",
                    "name": "安全工程师1",
                    "roles": ["safety_engineer"],
                    "skills": ["safety_check", "safety_tester"],
                    "lab_areas": ["safety_lab"],
                    "shift_id": "lab_day",
                    "max_parallel_assignments": 2,
                }
            ],
            "shifts": [{"shift_id": "lab_day", "start": "09:00", "end": "18:00"}],
            "preprocessing_resources": [],
            "transfer_resources": [],
            "transfer_matrix": {},
            "consumables": {},
            "maintenance_windows": [],
            "failure_events": [],
        },
    )

    schedule = QueueService(simulation).rebuild_schedule([order])

    step = schedule["scheduled_orders"][0]["steps"][0]
    assert step["equipment_id"] == "safety_tester-fast"
    assert step["duration_minutes"] == 75
    assert step["constraint_detail"]["equipment_performance_factor"] == 0.75
    assert schedule["metrics"]["equipment_heterogeneity_applied_count"] == 1


def test_synthetic_dataset_contains_lifecycle_events_retests_and_credibility_fields(tmp_path):
    result = generate_dataset(tmp_path)

    assert result["order_count"] > 0
    lifecycle_path = tmp_path / "order_lifecycle_events.json"
    assert lifecycle_path.exists()

    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    equipment = json.loads((tmp_path / "equipment_catalog.json").read_text(encoding="utf-8"))
    operations = json.loads((tmp_path / "operations_constraints.json").read_text(encoding="utf-8"))
    orders = json.loads((tmp_path / "order_arrivals.json").read_text(encoding="utf-8"))["orders"]

    assert {"order_cancelled", "order_updated", "detection_failed", "retest_created"}.issubset(
        {event["event_type"] for event in lifecycle["events"]}
    )
    retests = [order for order in orders if order.get("parent_order_id")]
    assert retests
    assert all(order.get("retest_reason") for order in retests)
    env_steps = [
        step
        for order in orders
        for step in order.get("detection_route", [])
        if step["project_type"] == "environmental_check"
    ]
    assert any(step.get("continuous_operation") and step["duration_minutes"] >= 24 * 60 for step in env_steps)
    assert any("performance_factor" in instance for item in equipment["equipment_types"] for instance in item["instances"])
    assert any(employee.get("unavailable_windows") for employee in operations["employees"])
