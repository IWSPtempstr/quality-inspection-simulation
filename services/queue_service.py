from __future__ import annotations

from math import ceil
from typing import Iterable

from domain.schemas import OrderType, QueueStatus
from services.simulation_service import SimulationService


class QueueService:
    """Queue scheduling service for simulated laboratory orders."""

    PRIORITY = {
        OrderType.VIP: 0,
        OrderType.URGENT: 1,
        OrderType.NORMAL: 2,
    }

    def __init__(self, simulation_service: SimulationService | None = None) -> None:
        self.simulation = simulation_service or SimulationService()
        self.last_schedule: dict = {
            "scheduled_orders": [],
            "blocked_orders": [],
            "equipment_status": self.simulation.equipment_status_summary(),
        }

    def sort_orders(self, orders: Iterable[dict]) -> list[dict]:
        return sorted(
            orders,
            key=lambda order: (
                self.PRIORITY[self._order_type(order["order_type"])],
                order["created_at"],
            ),
        )

    def rebuild_schedule(self, orders: Iterable[dict]) -> dict:
        self.simulation.reset_runtime_state()
        availability: dict[str, int] = {}
        scheduled_orders: list[dict] = []
        blocked_orders: list[dict] = []

        for order in self.sort_orders(orders):
            if order.get("status") == QueueStatus.CANCELLED:
                continue

            flow = self.simulation.get_detection_flow(
                order["certification_type"],
                order.get("requested_projects") or [],
            )
            if not flow:
                blocked_orders.append(
                    {
                        **self._serialize_order(order),
                        "status": QueueStatus.BLOCKED,
                        "reason": f"no detection flow for {order['certification_type']}",
                    }
                )
                continue

            previous_end = 0
            steps: list[dict] = []
            blocked_reason = ""
            for project in flow:
                equipment_type = project["equipment_type"]
                capacity = self.simulation.equipment_capacity(equipment_type)
                if capacity <= 0:
                    blocked_reason = f"required equipment unavailable: {equipment_type}"
                    break

                required_batches = ceil(order["sample_quantity"] / capacity)
                start_minute = max(previous_end, availability.get(equipment_type, 0))
                duration_minutes = project["duration_minutes"] * required_batches
                end_minute = start_minute + duration_minutes
                availability[equipment_type] = end_minute
                previous_end = end_minute

                steps.append(
                    {
                        "project_id": project["id"],
                        "project_type": project["project_type"],
                        "equipment_type": equipment_type,
                        "sequence": project["sequence"],
                        "start_minute": start_minute,
                        "duration_minutes": duration_minutes,
                        "end_minute": end_minute,
                        "batch_count": min(capacity, order["sample_quantity"]),
                        "required_batches": required_batches,
                    }
                )

            if blocked_reason:
                blocked_orders.append(
                    {
                        **self._serialize_order(order),
                        "status": QueueStatus.BLOCKED,
                        "reason": blocked_reason,
                    }
                )
                continue

            scheduled_orders.append(
                {
                    **self._serialize_order(order),
                    "status": QueueStatus.SCHEDULED,
                    "steps": steps,
                    "estimated_finish_minute": previous_end,
                }
            )

        self.last_schedule = {
            "scheduled_orders": scheduled_orders,
            "blocked_orders": blocked_orders,
            "equipment_status": self.simulation.equipment_status_summary(),
        }
        return self.last_schedule

    def snapshot(self) -> dict:
        scheduled = self.last_schedule.get("scheduled_orders", [])
        blocked = self.last_schedule.get("blocked_orders", [])
        type_distribution: dict[str, int] = {}
        for order in scheduled + blocked:
            key = self._enum_value(order["order_type"])
            type_distribution[key] = type_distribution.get(key, 0) + 1
        return {
            "queue_length": len(scheduled),
            "blocked_count": len(blocked),
            "order_type_distribution": type_distribution,
            "equipment_load": self.last_schedule.get("equipment_status", self.simulation.equipment_status_summary()),
            "scheduled_orders": scheduled,
            "blocked_orders": blocked,
        }

    def _order_type(self, value: OrderType | str) -> OrderType:
        return value if isinstance(value, OrderType) else OrderType(value)

    def _enum_value(self, value):
        return value.value if hasattr(value, "value") else value

    def _serialize_order(self, order: dict) -> dict:
        return {
            **order,
            "order_type": self._enum_value(order["order_type"]),
            "certification_type": self._enum_value(order["certification_type"]),
            "status": self._enum_value(order["status"]),
        }

