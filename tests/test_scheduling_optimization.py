from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from domain.schemas import CertificationType, OrderType, QueueStatus
from scripts.scheduling_optimization_utils import (
    capacity_report_for_dataset,
    derive_optimized_dataset,
    evaluate_dataset,
)
from services.queue_service import QueueService
from services.scheduler_service import ScheduleOptimizerService
from services.simulation_service import SimulationService


TZ = timezone(timedelta(hours=8))


def _order(order_id: str, arrival: datetime, promised_days: int = 7) -> dict:
    return {
        "id": order_id,
        "order_type": OrderType.NORMAL,
        "sample_name": f"{order_id}样品",
        "sample_quantity": 1,
        "certification_type": CertificationType.CCC,
        "requested_projects": [],
        "status": QueueStatus.PENDING,
        "arrival_time": arrival,
        "promised_finish_time": arrival + timedelta(days=promised_days),
        "created_at": arrival,
        "updated_at": arrival,
    }


def _single_step_order(
    order_id: str,
    order_type: OrderType,
    arrival: datetime,
    duration_minutes: int,
    promised_finish_time: datetime,
) -> dict:
    order = _order(order_id, arrival)
    order["order_type"] = order_type
    order["promised_finish_time"] = promised_finish_time
    order["detection_route"] = [
        {
            "project_id": f"{order_id}-safety",
            "project_type": "safety_check",
            "equipment_type": "safety_tester",
            "lab_area": "safety_lab",
            "sequence": 1,
            "duration_minutes": duration_minutes,
            "setup_minutes": 0,
            "operator_requirements": {
                "required_operator_count": 1,
                "required_roles": ["safety_engineer"],
                "supervision_mode": "shared_supervision",
                "staff_phase": "running",
            },
        }
    ]
    return order


def test_simulation_service_can_load_dataset_equipment_catalog_instances():
    equipment_catalog = {
        "equipment_types": [
            {
                "equipment_type": "emc_tester",
                "d": 3,
                "capacity_n": 1,
                "lab_area": "emc_lab",
                "supported_project_types": ["emc_check"],
                "instances": [
                    {
                        "equipment_id": f"emc_tester-{index}",
                        "equipment_type": "emc_tester",
                        "status": "idle",
                        "capacity_n": 1,
                        "lab_area": "emc_lab",
                    }
                    for index in range(1, 4)
                ],
            }
        ]
    }

    simulation = SimulationService(equipment_catalog=equipment_catalog)

    assert len(simulation.equipment_instances_for("emc_tester")) == 3
    assert simulation.equipment_status_summary()["emc_tester"]["total"] == 3


def test_sla_guarded_score_prefers_fewer_vip_and_urgent_delayed_orders():
    optimizer = ScheduleOptimizerService(QueueService(SimulationService()))
    vip_protected = {
        "metrics": {
            "blocked_count": 0,
            "vip_delayed_count": 0,
            "urgent_delayed_count": 1,
            "normal_delayed_count": 3,
            "vip_delay_minutes": 0,
            "urgent_delay_minutes": 100,
            "normal_delay_minutes": 900,
            "total_delay_minutes": 1000,
            "average_wait_minutes": 40,
            "equipment_idle_penalty": 20,
        }
    }
    vip_delayed = {
        "metrics": {
            "blocked_count": 0,
            "vip_delayed_count": 1,
            "urgent_delayed_count": 0,
            "normal_delayed_count": 0,
            "vip_delay_minutes": 60,
            "urgent_delay_minutes": 0,
            "normal_delay_minutes": 0,
            "total_delay_minutes": 60,
            "average_wait_minutes": 10,
            "equipment_idle_penalty": 20,
        }
    }

    assert "sla_guarded_hybrid" in optimizer.STRATEGIES
    assert optimizer._score_schedule(vip_protected) < optimizer._score_schedule(vip_delayed)


def test_rolling_horizon_keeps_far_future_orders_as_forecast_only():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    near = _order("near", arrival)
    far = _order("far", arrival + timedelta(days=30))

    schedule = QueueService(SimulationService()).rebuild_schedule(
        [near, far],
        strategy="sla_guarded_hybrid",
        rolling_horizon_days=7,
    )

    assert [item["id"] for item in schedule["scheduled_orders"]] == ["near"]
    assert [item["id"] for item in schedule["forecast_orders"]] == ["far"]
    assert schedule["metrics"]["forecast_count"] == 1


def test_sla_guarded_strategy_can_hold_capacity_for_imminent_vip_deadline():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    orders = [
        _single_step_order(
            "normal-long",
            OrderType.NORMAL,
            arrival,
            180,
            arrival + timedelta(days=7),
        ),
        _single_step_order(
            "vip-short",
            OrderType.VIP,
            arrival + timedelta(hours=1),
            120,
            arrival + timedelta(hours=3, minutes=30),
        ),
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
                    "shift_id": "lab_day",
                    "max_parallel_assignments": 1,
                }
            ],
            "preprocessing_resources": [],
            "transfer_resources": [],
            "transfer_matrix": {},
            "consumables": {},
            "maintenance_windows": [],
            "failure_events": [],
        },
    )

    baseline = QueueService(simulation).rebuild_schedule(orders, strategy="priority_fifo")
    optimized = QueueService(simulation).rebuild_schedule(orders, strategy="sla_guarded_hybrid")

    baseline_vip = next(order for order in baseline["scheduled_orders"] if order["id"] == "vip-short")
    optimized_vip = next(order for order in optimized["scheduled_orders"] if order["id"] == "vip-short")
    assert baseline_vip["sla_status"] == "delayed"
    assert optimized_vip["sla_status"] == "on_time"
    assert [order["id"] for order in optimized["scheduled_orders"]] == ["vip-short", "normal-long"]


def test_sla_guarded_scheduler_interleaves_ready_steps_across_orders():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    order_a = _order("normal-a", arrival)
    order_b = _order("normal-b", arrival)
    order_a["order_type"] = OrderType.VIP
    order_b["order_type"] = OrderType.NORMAL
    order_a["promised_finish_time"] = arrival + timedelta(days=7)
    order_b["promised_finish_time"] = arrival + timedelta(hours=2)
    order_a["detection_route"] = [
        {
            "project_id": "a-safety",
            "project_type": "safety_check",
            "equipment_type": "safety_tester",
            "lab_area": "safety_lab",
            "sequence": 1,
            "duration_minutes": 60,
            "operator_requirements": {
                "required_operator_count": 1,
                "required_roles": ["safety_engineer"],
                "supervision_mode": "shared_supervision",
                "staff_phase": "running",
            },
        },
        {
            "project_id": "a-emc",
            "project_type": "emc_check",
            "equipment_type": "emc_tester",
            "lab_area": "emc_lab",
            "sequence": 2,
            "duration_minutes": 120,
            "operator_requirements": {
                "required_operator_count": 1,
                "required_roles": ["emc_engineer"],
                "supervision_mode": "exclusive",
                "staff_phase": "running",
            },
        },
    ]
    order_b["detection_route"] = [
        {
            "project_id": "b-emc",
            "project_type": "emc_check",
            "equipment_type": "emc_tester",
            "lab_area": "emc_lab",
            "sequence": 1,
            "duration_minutes": 90,
            "operator_requirements": {
                "required_operator_count": 1,
                "required_roles": ["emc_engineer"],
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
                },
                {
                    "equipment_type": "emc_tester",
                    "d": 1,
                    "capacity_n": 1,
                    "lab_area": "emc_lab",
                    "supported_project_types": ["emc_check"],
                    "instances": [
                        {
                            "equipment_id": "emc_tester-1",
                            "equipment_type": "emc_tester",
                            "status": "idle",
                            "capacity_n": 1,
                            "lab_area": "emc_lab",
                        }
                    ],
                },
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
                    "max_parallel_assignments": 1,
                },
                {
                    "employee_id": "emp-emc-1",
                    "name": "EMC工程师1",
                    "roles": ["emc_engineer"],
                    "skills": ["emc_check", "emc_tester"],
                    "lab_areas": ["emc_lab"],
                    "shift_id": "lab_day",
                    "max_parallel_assignments": 1,
                },
            ],
            "preprocessing_resources": [],
            "transfer_resources": [],
            "transfer_matrix": {},
            "consumables": {},
            "maintenance_windows": [],
            "failure_events": [],
        },
    )

    optimized = QueueService(simulation).rebuild_schedule([order_a, order_b], strategy="sla_guarded_hybrid")

    by_order = {order["id"]: order for order in optimized["scheduled_orders"]}
    a_safety = next(step for step in by_order["normal-a"]["steps"] if step["equipment_type"] == "safety_tester")
    a_emc = next(step for step in by_order["normal-a"]["steps"] if step["equipment_type"] == "emc_tester")
    b_emc = next(step for step in by_order["normal-b"]["steps"] if step["equipment_type"] == "emc_tester")
    assert a_safety["start_time"] < b_emc["end_time"]
    assert b_emc["start_time"] < a_emc["start_time"]
    assert a_emc["start_time"] >= b_emc["end_time"]
    assert by_order["normal-b"]["sla_status"] == "on_time"


def test_capacity_report_identifies_existing_large_dataset_as_stress_load():
    report = capacity_report_for_dataset(Path("data/scenario_synthetic_center_large"))

    assert report["scenario_label"] == "stress_load"
    assert report["equipment"]["environmental_chamber"]["load_factor"] > 1.0
    assert report["equipment"]["emc_tester"]["recommended_instances_for_90pct"] > 2


def test_derived_optimized_dataset_has_dynamic_sla_and_expected_capacity_band(tmp_path):
    output_dir = tmp_path / "balanced"

    report = derive_optimized_dataset(
        source_dir=Path("data/scenario_synthetic_center_large"),
        output_dir=output_dir,
        scenario="balanced",
    )
    capacity = capacity_report_for_dataset(output_dir)

    assert report["scenario_label"] == "normal_load"
    assert capacity["scenario_label"] == "normal_load"
    assert 0.60 <= capacity["average_load_factor"] <= 0.80
    assert (output_dir / "order_arrivals.json").exists()
    assert report["dynamic_sla"]["enabled"] is True


def test_evaluate_dataset_returns_metrics_and_supports_peak_sampling(tmp_path):
    output_dir = tmp_path / "highload"
    derive_optimized_dataset(
        source_dir=Path("data/scenario_synthetic_center_large"),
        output_dir=output_dir,
        scenario="highload",
    )

    report = evaluate_dataset(output_dir, integration_order_limit=20, sample_mode="head")

    assert report["sample_mode"] == "head"
    assert report["created_orders"] == 20
    assert "priority_fifo" in report["strategy_results"]
    assert "sla_guarded_hybrid" in report["strategy_results"]
    assert "rebuild_latency_avg_ms" in report["comparison"]
    assert report["agent_handoff"]["visited_agents"] == [
        "orchestrator",
        "queue_scheduler",
        "equipment_monitor",
    ]


def test_step_pool_scheduler_does_not_block_spread_sample_orders():
    report = evaluate_dataset(
        Path("data/scenario_synthetic_center_highload_5000"),
        integration_order_limit=100,
        sample_mode="spread",
    )

    metrics = report["strategy_results"]["sla_guarded_hybrid"]["metrics"]
    assert metrics["step_level_scheduling"] is True
    assert metrics["blocked_count"] == 0
