from __future__ import annotations

from collections import OrderedDict


def format_schedule_summary(run: dict) -> dict:
    return {
        "id": run["id"],
        "scheduled_count": run["scheduled_count"],
        "blocked_count": run["blocked_count"],
        "created_at": _serialize(run.get("created_at")),
    }


def format_schedule_detail(schedule: dict) -> dict:
    orders: "OrderedDict[str, dict]" = OrderedDict()
    blocked_orders: list[dict] = []

    for step in schedule.get("steps", []):
        status = step.get("status")
        if status == "blocked":
            blocked_orders.append(
                {
                    "id": step["order_id"],
                    "order_type": step["order_type"],
                    "sample_name": step["sample_name"],
                    "certification_type": step["certification_type"],
                    "status": status,
                    "reason": step.get("blocked_reason"),
                }
            )
            continue

        order = orders.setdefault(
            step["order_id"],
            {
                "id": step["order_id"],
                "order_type": step["order_type"],
                "sample_name": step["sample_name"],
                "certification_type": step["certification_type"],
                "status": status,
                "arrival_time": _serialize(step.get("arrival_time")),
                "promised_finish_time": _serialize(step.get("promised_finish_time")),
                "sla_status": step.get("sla_status"),
                "delay_minutes": step.get("delay_minutes"),
                "steps": [],
            },
        )
        if step.get("project_id"):
            order["steps"].append(
                {
                    "project_id": step.get("project_id"),
                    "project_type": step.get("project_type"),
                    "equipment_type": step.get("equipment_type"),
                    "equipment_id": step.get("equipment_id"),
                    "sequence": step.get("sequence"),
                    "start_minute": step.get("start_minute"),
                    "start_time": _serialize(step.get("start_time")),
                    "duration_minutes": step.get("duration_minutes"),
                    "end_minute": step.get("end_minute"),
                    "end_time": _serialize(step.get("end_time")),
                    "batch_count": step.get("batch_count"),
                    "required_batches": step.get("required_batches"),
                }
            )

    return {
        "id": schedule["id"],
        "scheduled_count": schedule["scheduled_count"],
        "blocked_count": schedule["blocked_count"],
        "created_at": _serialize(schedule.get("created_at")),
        "metrics": schedule.get("metrics", {}),
        "scheduled_orders": list(orders.values()),
        "blocked_orders": blocked_orders,
        "steps": schedule.get("steps", []),
    }


def _serialize(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
