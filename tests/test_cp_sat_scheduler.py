from __future__ import annotations

from datetime import datetime, timedelta, timezone

from domain.schemas import CertificationType, OrderType, QueueStatus
from services.queue_service import QueueService
from services.scheduler_service import ScheduleOptimizerService
from services.simulation_service import SimulationService


TZ = timezone(timedelta(hours=8))


def _single_step_order(
    order_id: str,
    order_type: OrderType,
    arrival: datetime,
    duration_minutes: int,
    promised_finish_time: datetime,
) -> dict:
    return {
        "id": order_id,
        "order_type": order_type,
        "sample_name": f"{order_id}样品",
        "sample_quantity": 1,
        "certification_type": CertificationType.CCC,
        "requested_projects": [],
        "status": QueueStatus.PENDING,
        "arrival_time": arrival,
        "promised_finish_time": promised_finish_time,
        "created_at": arrival,
        "updated_at": arrival,
        "detection_route": [
            {
                "project_id": f"{order_id}-safety",
                "project_type": "safety_check",
                "equipment_type": "safety_tester",
                "lab_area": "safety_lab",
                "sequence": 1,
                "duration_minutes": duration_minutes,
                "operator_requirements": {
                    "required_operator_count": 1,
                    "required_roles": ["safety_engineer"],
                    "supervision_mode": "exclusive",
                    "staff_phase": "running",
                },
            }
        ],
    }


def _single_equipment_simulation() -> SimulationService:
    return SimulationService(
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
            "shifts": [{"shift_id": "lab_day", "start": "09:00", "end": "18:00"}],
            "preprocessing_resources": [],
            "transfer_resources": [],
            "transfer_matrix": {},
            "consumables": {},
            "maintenance_windows": [],
            "failure_events": [],
        },
    )


def _support_simulation() -> SimulationService:
    return SimulationService(
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
                    "employee_id": "emp-prep-1",
                    "name": "前处理员1",
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
            "shifts": [{"shift_id": "lab_day", "start": "09:00", "end": "18:00"}],
            "preprocessing_resources": [{"resource_id": "prep-1", "resource_type": "prep_station"}],
            "transfer_resources": [{"resource_id": "cart-1", "resource_type": "transfer_cart"}],
            "transfer_matrix": {
                "intake->safety_lab": {"duration_minutes": 8, "required_roles": ["transfer_operator"], "resource_type": "transfer_cart"},
                "safety_lab->emc_lab": {"duration_minutes": 10, "required_roles": ["transfer_operator"], "resource_type": "transfer_cart"},
            },
            "consumables": {},
            "maintenance_windows": [],
            "failure_events": [],
        },
    )


def test_cp_sat_rolling_strategy_schedules_vip_before_normal_when_sla_is_at_risk():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    orders = [
        _single_step_order(
            "normal-long",
            OrderType.NORMAL,
            arrival,
            180,
            arrival + timedelta(days=5),
        ),
        _single_step_order(
            "vip-risk",
            OrderType.VIP,
            arrival,
            60,
            arrival + timedelta(hours=2),
        ),
    ]

    schedule = QueueService(_single_equipment_simulation()).rebuild_schedule(orders, strategy="cp_sat_rolling")

    assert schedule["metrics"]["solver_used"] == "cp_sat"
    assert schedule["metrics"]["solver_status"] in {"optimal", "feasible"}
    assert schedule["metrics"]["fallback_used"] is False
    assert [order["id"] for order in schedule["scheduled_orders"]] == ["vip-risk", "normal-long"]
    assert schedule["scheduled_orders"][0]["steps"][0]["equipment_id"] == "safety_tester-1"
    assert schedule["scheduled_orders"][0]["sla_status"] == "on_time"


def test_cp_sat_v2_does_not_start_before_arrival_when_arrival_has_seconds():
    origin_arrival = datetime(2026, 6, 1, 9, 46, 44, tzinfo=TZ)
    later_arrival = datetime(2026, 6, 1, 9, 47, 6, tzinfo=TZ)
    first = _single_step_order(
        "origin-order",
        OrderType.NORMAL,
        origin_arrival,
        10,
        origin_arrival + timedelta(days=1),
    )
    second = _single_step_order(
        "second-precision",
        OrderType.VIP,
        later_arrival,
        30,
        later_arrival + timedelta(days=1),
    )

    schedule = QueueService(_single_equipment_simulation()).rebuild_schedule([first, second], strategy="cp_sat_rolling")

    scheduled = {item["id"]: item for item in schedule["scheduled_orders"]}
    step_start = datetime.fromisoformat(scheduled["second-precision"]["steps"][0]["start_time"])
    assert schedule["metrics"]["fallback_used"] is False
    assert step_start >= later_arrival


def test_cp_sat_v2_keeps_non_continuous_detection_inside_workday():
    arrival = datetime(2026, 6, 1, 17, 30, tzinfo=TZ)
    order = _single_step_order(
        "late-workday",
        OrderType.NORMAL,
        arrival,
        90,
        arrival + timedelta(days=2),
    )

    schedule = QueueService(_single_equipment_simulation()).rebuild_schedule([order], strategy="cp_sat_rolling")

    step = schedule["scheduled_orders"][0]["steps"][0]
    start = datetime.fromisoformat(step["start_time"])
    end = datetime.fromisoformat(step["end_time"])
    assert schedule["metrics"]["fallback_used"] is False
    assert start.hour >= 9
    assert end.hour < 18 or (end.hour == 18 and end.minute == 0 and end.second == 0)
    assert start.date() == datetime(2026, 6, 2, tzinfo=TZ).date()


def test_cp_sat_strategy_falls_back_to_rules_when_no_supported_route_exists():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    order = _single_step_order(
        "unsupported",
        OrderType.VIP,
        arrival,
        60,
        arrival + timedelta(days=1),
    )
    order["detection_route"][0]["equipment_type"] = "missing_equipment"

    schedule = QueueService(_single_equipment_simulation()).rebuild_schedule([order], strategy="cp_sat_rolling")

    assert schedule["metrics"]["solver_used"] == "cp_sat"
    assert schedule["metrics"]["fallback_used"] is True
    assert schedule["metrics"]["fallback_reason"]
    assert schedule["blocked_orders"][0]["id"] == "unsupported"


def test_optimizer_includes_cp_sat_candidate_scores():
    optimizer = ScheduleOptimizerService(QueueService(_single_equipment_simulation()))
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    orders = [
        _single_step_order("vip", OrderType.VIP, arrival, 30, arrival + timedelta(hours=1)),
        _single_step_order("normal", OrderType.NORMAL, arrival, 30, arrival + timedelta(days=3)),
    ]

    analysis = optimizer.analyze(orders)

    assert "cp_sat_rolling" in optimizer.STRATEGIES
    assert "cp_sat_rolling" in analysis["candidate_scores"]
    assert analysis["candidates"]["cp_sat_rolling"]["metrics"]["solver_used"] == "cp_sat"


def test_cp_sat_v2_schedules_preprocessing_transfer_and_detection_without_fallback():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    order = _single_step_order("support-order", OrderType.VIP, arrival, 30, arrival + timedelta(days=2))
    order["preprocessing_profile"] = {
        "required_minutes": 20,
        "lab_area": "intake",
        "required_roles": ["sample_operator"],
        "resource_type": "prep_station",
        "required_operator_count": 1,
    }
    order["detection_route"] = [
        {
            "project_id": "support-safety",
            "project_type": "safety_check",
            "equipment_type": "safety_tester",
            "lab_area": "safety_lab",
            "sequence": 1,
            "duration_minutes": 30,
            "operator_requirements": {
                "required_operator_count": 1,
                "required_roles": ["safety_engineer"],
                "supervision_mode": "exclusive",
                "staff_phase": "running",
            },
        },
        {
            "project_id": "support-emc",
            "project_type": "emc_check",
            "equipment_type": "emc_tester",
            "lab_area": "emc_lab",
            "sequence": 2,
            "duration_minutes": 30,
            "operator_requirements": {
                "required_operator_count": 1,
                "required_roles": ["emc_engineer"],
                "supervision_mode": "exclusive",
                "staff_phase": "running",
            },
        },
    ]

    schedule = QueueService(_support_simulation()).rebuild_schedule([order], strategy="cp_sat_rolling")

    assert schedule["metrics"]["solver_status"] in {"optimal", "feasible"}
    assert schedule["metrics"]["fallback_used"] is False
    steps = schedule["scheduled_orders"][0]["steps"]
    assert [step["step_kind"] for step in steps] == ["preprocessing", "transfer", "detection", "transfer", "detection"]
    assert steps[0]["resource_ids"] == ["prep-1"]
    assert steps[1]["resource_ids"] == ["cart-1"]


def test_cp_sat_v2_respects_consumable_daily_capacity_window():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    first = _single_step_order("fixture-a", OrderType.NORMAL, arrival, 60, arrival + timedelta(days=3))
    second = _single_step_order("fixture-b", OrderType.NORMAL, arrival, 60, arrival + timedelta(days=3))
    for order in (first, second):
        order["detection_route"][0]["consumable_type"] = "rare_fixture"
        order["detection_route"][0]["consumable_units_per_batch"] = 1
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
                        {"equipment_id": "safety_tester-1", "equipment_type": "safety_tester", "status": "idle", "capacity_n": 1, "lab_area": "safety_lab"},
                        {"equipment_id": "safety_tester-2", "equipment_type": "safety_tester", "status": "idle", "capacity_n": 1, "lab_area": "safety_lab"},
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
                },
                {
                    "employee_id": "emp-safety-2",
                    "name": "安全工程师2",
                    "roles": ["safety_engineer"],
                    "skills": ["safety_check", "safety_tester"],
                    "lab_areas": ["safety_lab"],
                    "shift_id": "lab_day",
                    "max_parallel_assignments": 1,
                },
            ],
            "shifts": [{"shift_id": "lab_day", "start": "09:00", "end": "18:00"}],
            "preprocessing_resources": [],
            "transfer_resources": [],
            "transfer_matrix": {},
            "consumables": {"rare_fixture": {"daily_capacity": 1}},
            "maintenance_windows": [],
            "failure_events": [],
        },
    )

    schedule = QueueService(simulation).rebuild_schedule([first, second], strategy="cp_sat_rolling")

    starts = sorted(datetime.fromisoformat(order["steps"][0]["start_time"]) for order in schedule["scheduled_orders"])
    assert schedule["metrics"]["fallback_used"] is False
    assert starts[1] >= starts[0] + timedelta(hours=24)


def test_cp_sat_v2_models_setup_unload_staff_separately_from_continuous_equipment():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    orders = []
    for suffix in ("a", "b"):
        order = _single_step_order(f"env-{suffix}", OrderType.NORMAL, arrival, 2880, arrival + timedelta(days=10))
        order["detection_route"] = [
            {
                "project_id": f"env-{suffix}",
                "project_type": "environmental_check",
                "equipment_type": "environmental_chamber",
                "lab_area": "environmental_lab",
                "sequence": 1,
                "duration_minutes": 2880,
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
        ]
        orders.append(order)
    simulation = SimulationService(
        equipment_catalog={
            "equipment_types": [
                {
                    "equipment_type": "environmental_chamber",
                    "d": 2,
                    "capacity_n": 1,
                    "lab_area": "environmental_lab",
                    "supported_project_types": ["environmental_check"],
                    "instances": [
                        {"equipment_id": "environmental_chamber-1", "equipment_type": "environmental_chamber", "status": "idle", "capacity_n": 1, "lab_area": "environmental_lab"},
                        {"equipment_id": "environmental_chamber-2", "equipment_type": "environmental_chamber", "status": "idle", "capacity_n": 1, "lab_area": "environmental_lab"},
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
                    "shift_id": "continuous",
                    "max_parallel_assignments": 1,
                }
            ],
            "shifts": [{"shift_id": "continuous", "start": "00:00", "end": "23:59"}],
            "preprocessing_resources": [],
            "transfer_resources": [],
            "transfer_matrix": {},
            "consumables": {},
            "maintenance_windows": [],
            "failure_events": [],
        },
    )

    schedule = QueueService(simulation).rebuild_schedule(orders, strategy="cp_sat_rolling")

    steps = sorted((order["steps"][0] for order in schedule["scheduled_orders"]), key=lambda item: item["start_time"])
    assert schedule["metrics"]["fallback_used"] is False
    assert datetime.fromisoformat(steps[1]["start_time"]) < datetime.fromisoformat(steps[0]["end_time"])
    assert steps[0]["constraint_detail"]["staff_windows"][0]["end_time"] < steps[0]["end_time"]
    assert steps[0]["constraint_detail"]["staff_windows"][1]["start_time"] > steps[0]["start_time"]


def test_cp_sat_v2_locks_running_step_resource_windows():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    order = _single_step_order("after-lock", OrderType.VIP, arrival, 60, arrival + timedelta(days=1))
    locked_steps = [
        {
            "step_kind": "detection",
            "equipment_id": "safety_tester-1",
            "resource_ids": [],
            "assigned_employee_ids": ["emp-safety-1"],
            "lab_area": "safety_lab",
            "project_type": "safety_check",
            "start_time": "2026-06-01T09:00:00+08:00",
            "end_time": "2026-06-01T11:00:00+08:00",
        }
    ]

    schedule = QueueService(_single_equipment_simulation()).rebuild_schedule(
        [order],
        strategy="cp_sat_rolling",
        locked_steps=locked_steps,
    )

    step = schedule["scheduled_orders"][0]["steps"][0]
    assert schedule["metrics"]["fallback_used"] is False
    assert schedule["metrics"]["locked_step_count"] == 1
    assert step["start_time"] >= "2026-06-01T11:00:00+08:00"


def test_cp_sat_v2_keeps_far_future_orders_as_forecast_in_rolling_window():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    near = _single_step_order("near", OrderType.VIP, arrival, 30, arrival + timedelta(days=1))
    far = _single_step_order("far", OrderType.NORMAL, arrival + timedelta(days=20), 30, arrival + timedelta(days=25))

    schedule = QueueService(_single_equipment_simulation()).rebuild_schedule(
        [near, far],
        strategy="cp_sat_rolling",
        rolling_horizon_days=7,
    )

    assert [order["id"] for order in schedule["scheduled_orders"]] == ["near"]
    assert [order["id"] for order in schedule["forecast_orders"]] == ["far"]
    assert schedule["metrics"]["forecast_count"] == 1
    assert schedule["metrics"]["solver_status"] in {"optimal", "feasible"}


def test_cp_sat_v2_caps_large_rolling_window_and_optimizer_keeps_full_schedule(monkeypatch):
    monkeypatch.setenv("CP_SAT_MAX_ACTIVE_ORDERS", "2")
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    orders = [
        _single_step_order(f"order-{index}", OrderType.NORMAL, arrival + timedelta(minutes=index), 30, arrival + timedelta(days=2))
        for index in range(4)
    ]
    queue_service = QueueService(_single_equipment_simulation())

    direct = queue_service.rebuild_schedule(orders, strategy="cp_sat_rolling", rolling_horizon_days=7)
    analysis = ScheduleOptimizerService(QueueService(_single_equipment_simulation())).analyze(orders)

    assert direct["metrics"]["fallback_used"] is False
    assert direct["metrics"]["forecast_count"] == 2
    assert len(direct["scheduled_orders"]) == 2
    assert analysis["selected_strategy"] != "cp_sat_rolling"
    assert len(analysis["schedule"]["scheduled_orders"]) == 4


def test_cp_sat_v2_uses_full_order_set_when_capped_candidate_falls_back(monkeypatch):
    monkeypatch.setenv("CP_SAT_MAX_ACTIVE_ORDERS", "2")
    monkeypatch.setenv("CP_SAT_TIME_LIMIT_SECONDS", "0")
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    orders = [
        _single_step_order(f"fallback-{index}", OrderType.NORMAL, arrival + timedelta(minutes=index), 30, arrival + timedelta(days=2))
        for index in range(4)
    ]

    schedule = QueueService(_single_equipment_simulation()).rebuild_schedule(
        orders,
        strategy="cp_sat_rolling",
        rolling_horizon_days=7,
    )

    assert schedule["metrics"]["fallback_used"] is True
    assert len(schedule["scheduled_orders"]) == 4
