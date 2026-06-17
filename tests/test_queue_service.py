from datetime import datetime, timedelta, timezone

import pytest

from domain.schemas import CertificationType, OrderCreate, OrderType, QueueStatus
from services.queue_service import QueueService
from services.schedule_metrics import delay_minutes, delay_rate, rate, sla_rate, sla_status
from services.simulation_service import SimulationService


def _order(order_type: OrderType, minutes_ago: int, sample_name: str = "电热水壶"):
    now = datetime.now(timezone.utc)
    return {
        "id": f"order-{order_type.value}-{minutes_ago}",
        "order_type": order_type,
        "sample_name": sample_name,
        "sample_quantity": 2,
        "certification_type": CertificationType.CCC,
        "requested_projects": [],
        "status": QueueStatus.PENDING,
        "created_at": now - timedelta(minutes=minutes_ago),
        "updated_at": now - timedelta(minutes=minutes_ago),
    }


def test_orders_are_sorted_by_business_priority_then_created_time():
    service = QueueService(SimulationService())
    orders = [
        _order(OrderType.NORMAL, 30),
        _order(OrderType.VIP, 5),
        _order(OrderType.URGENT, 60),
        _order(OrderType.VIP, 20),
    ]

    sorted_orders = service.sort_orders(orders)

    assert [order["id"] for order in sorted_orders] == [
        "order-vip-20",
        "order-vip-5",
        "order-urgent-60",
        "order-normal-30",
    ]


def test_schedule_respects_detection_step_order_and_equipment_capacity():
    service = QueueService(SimulationService())
    order = _order(OrderType.VIP, 1)
    order["sample_quantity"] = 3

    result = service.rebuild_schedule([order])

    scheduled = result["scheduled_orders"]
    assert len(scheduled) == 1
    assert scheduled[0]["status"] == QueueStatus.SCHEDULED
    assert [step["sequence"] for step in scheduled[0]["steps"]] == [1, 2]
    assert all(step["batch_count"] == 2 for step in scheduled[0]["steps"])
    assert all(step["required_batches"] == 2 for step in scheduled[0]["steps"])
    assert scheduled[0]["steps"][0]["end_minute"] <= scheduled[0]["steps"][1]["start_minute"]


def test_schedule_marks_order_blocked_when_required_equipment_is_unavailable():
    simulation = SimulationService()
    simulation.set_equipment_offline("safety_tester")
    service = QueueService(simulation)

    result = service.rebuild_schedule([_order(OrderType.NORMAL, 1)])

    assert result["scheduled_orders"] == []
    assert result["blocked_orders"][0]["status"] == QueueStatus.BLOCKED
    assert "safety_tester" in result["blocked_orders"][0]["reason"]


def test_order_create_rejects_invalid_sample_quantity():
    with pytest.raises(ValueError):
        OrderCreate(
            order_type=OrderType.NORMAL,
            sample_name="插座",
            sample_quantity=0,
            certification_type=CertificationType.CVC,
        )


def test_schedule_metric_helpers_calculate_sla_and_delay_values():
    promised = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    assert sla_status(promised, promised) == "on_time"
    assert sla_status(promised + timedelta(minutes=1), promised) == "delayed"
    assert sla_status(promised, None) == "not_applicable"
    assert delay_minutes(promised + timedelta(minutes=75), promised) == 75
    assert delay_minutes(promised - timedelta(minutes=1), promised) == 0
    assert delay_minutes(promised, None) == 0
    assert rate(2, 3) == 0.6667
    assert rate(2, 0) == 0.0


def test_schedule_metric_helpers_calculate_rates_from_order_statuses():
    orders = [
        {"sla_status": "on_time"},
        {"sla_status": "delayed"},
        {"sla_status": "not_applicable"},
    ]

    assert sla_rate(orders) == 0.3333
    assert delay_rate(orders) == 0.3333
    assert sla_rate([]) == 1.0
    assert delay_rate([]) == 0.0


def test_queue_service_metric_methods_delegate_to_helper_behavior():
    service = QueueService(SimulationService())
    promised = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    finish = promised + timedelta(minutes=15)
    orders = [{"sla_status": "on_time"}, {"sla_status": "delayed"}]

    assert service._sla_status(finish, promised) == sla_status(finish, promised)
    assert service._delay_minutes(finish, promised) == delay_minutes(finish, promised)
    assert service._sla_rate(orders) == sla_rate(orders)
    assert service._delay_rate(orders) == delay_rate(orders)
