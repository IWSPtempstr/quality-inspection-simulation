from __future__ import annotations

from datetime import datetime, timedelta, timezone

from domain.schemas import CertificationType, OrderType, QueueStatus
from services.queue_service import QueueService
from services.simulation_service import SimulationService


TZ = timezone(timedelta(hours=8))


def _order(order_id: str, order_type: OrderType, arrival: datetime, quantity: int = 2):
    return {
        "id": order_id,
        "order_type": order_type,
        "sample_name": f"{order_id}样品",
        "sample_quantity": quantity,
        "certification_type": CertificationType.CCC,
        "requested_projects": ["ccc-safety"],
        "status": QueueStatus.PENDING,
        "arrival_time": arrival,
        "promised_finish_time": arrival + timedelta(days=2),
        "created_at": arrival,
        "updated_at": arrival,
    }


def test_scheduler_assigns_same_equipment_type_to_distinct_instances_in_parallel():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    service = QueueService(SimulationService())

    schedule = service.rebuild_schedule(
        [
            _order("order-a", OrderType.NORMAL, arrival),
            _order("order-b", OrderType.NORMAL, arrival),
        ]
    )

    first_steps = [order["steps"][0] for order in schedule["scheduled_orders"]]
    assert {step["equipment_id"] for step in first_steps} == {"safety_tester-1", "safety_tester-2"}
    assert max(step["start_minute"] for step in first_steps) == 0


def test_scheduler_avoids_maintenance_windows_and_marks_sla_status():
    operations = {
        "maintenance_windows": [
            {
                "equipment_id": "safety_tester-1",
                "start": "2026-06-01T09:00:00+08:00",
                "end": "2026-06-01T10:30:00+08:00",
            },
            {
                "equipment_id": "safety_tester-2",
                "start": "2026-06-01T09:00:00+08:00",
                "end": "2026-06-01T10:30:00+08:00",
            },
        ]
    }
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    order = _order("order-maint", OrderType.VIP, arrival)
    order["promised_finish_time"] = datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
    service = QueueService(SimulationService(operations_constraints=operations))

    schedule = service.rebuild_schedule([order])

    step = schedule["scheduled_orders"][0]["steps"][0]
    assert step["start_time"] >= "2026-06-01T10:30:00+08:00"
    assert schedule["scheduled_orders"][0]["sla_status"] == "delayed"
    assert schedule["metrics"]["vip_sla_rate"] == 0.0


def test_future_vip_does_not_reserve_equipment_before_earlier_arrivals():
    early_normal = _order(
        "early-normal",
        OrderType.NORMAL,
        datetime(2026, 6, 1, 9, 0, tzinfo=TZ),
    )
    early_normal["requested_projects"] = []
    late_vip = _order(
        "late-vip",
        OrderType.VIP,
        datetime(2026, 6, 10, 9, 0, tzinfo=TZ),
    )
    late_vip["requested_projects"] = []

    schedule = QueueService(SimulationService()).rebuild_schedule([early_normal, late_vip])
    normal = next(order for order in schedule["scheduled_orders"] if order["id"] == "early-normal")
    vip = next(order for order in schedule["scheduled_orders"] if order["id"] == "late-vip")
    normal_emc = next(step for step in normal["steps"] if step["equipment_type"] == "emc_tester")
    vip_emc = next(step for step in vip["steps"] if step["equipment_type"] == "emc_tester")

    assert normal_emc["end_time"] <= vip_emc["start_time"]


def test_non_continuous_detection_step_does_not_cross_workday_end():
    order = _order(
        "late-cvc",
        OrderType.NORMAL,
        datetime(2026, 6, 1, 17, 30, tzinfo=TZ),
    )
    order["certification_type"] = CertificationType.CVC
    order["requested_projects"] = ["cvc-performance"]

    schedule = QueueService(SimulationService()).rebuild_schedule([order])
    step = schedule["scheduled_orders"][0]["steps"][0]

    assert step["start_time"] == "2026-06-02T09:00:00+08:00"
    assert step["end_time"] == "2026-06-02T09:40:00+08:00"


def test_schedule_metrics_include_wait_utilization_and_blocked_reason_distribution():
    arrival = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
    blocked = _order("blocked", OrderType.NORMAL, arrival)
    blocked["requested_projects"] = ["missing-project"]
    service = QueueService(SimulationService())

    schedule = service.rebuild_schedule([_order("ok", OrderType.VIP, arrival, quantity=8), blocked])

    metrics = schedule["metrics"]
    assert metrics["average_wait_minutes"] >= 0
    assert metrics["equipment_utilization"]
    assert metrics["blocked_reason_distribution"]["no detection flow for ccc"] == 1
    assert metrics["scheduled_count"] == 1
    assert metrics["blocked_count"] == 1
