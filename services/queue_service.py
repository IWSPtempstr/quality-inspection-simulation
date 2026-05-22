from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta, timezone
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
    DEFAULT_TZ = timezone(timedelta(hours=8))

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
                self._order_arrival_time(order),
            ),
        )

    def rebuild_schedule(self, orders: Iterable[dict]) -> dict:
        self.simulation.reset_runtime_state()
        active_orders = [order for order in orders if order.get("status") != QueueStatus.CANCELLED]
        schedule_origin = self._schedule_origin(active_orders)
        availability: dict[str, datetime] = {
            item["id"]: schedule_origin
            for item in self.simulation.list_equipment()
            if self._enum_value(item["status"]) != "offline"
        }
        busy_minutes: Counter[str] = Counter()
        scheduled_orders: list[dict] = []
        blocked_orders: list[dict] = []

        unscheduled_orders = list(active_orders)
        while unscheduled_orders:
            order = self._select_next_order(unscheduled_orders, availability, schedule_origin)
            unscheduled_orders.remove(order)
            flow = self._detection_flow_for_order(order)
            if not flow:
                blocked_orders.append(
                    {
                        **self._serialize_order(order),
                        "status": QueueStatus.BLOCKED,
                        "reason": f"no detection flow for {self._enum_value(order['certification_type'])}",
                    }
                )
                continue

            arrival_time = self._order_arrival_time(order)
            previous_end_time = self._next_work_start(self._order_release_time(order, schedule_origin))
            steps: list[dict] = []
            blocked_reason = ""
            for project in flow:
                equipment_type = project["equipment_type"]
                equipment_instances = self.simulation.equipment_instances_for(equipment_type)
                if not equipment_instances:
                    blocked_reason = f"required equipment unavailable: {equipment_type}"
                    break

                candidate = self._select_equipment_instance(
                    equipment_instances=equipment_instances,
                    availability=availability,
                    earliest_start=previous_end_time,
                    duration_base=project["duration_minutes"],
                    project_type=project["project_type"],
                    duration_is_total=bool(project.get("duration_is_total")),
                    sample_quantity=order["sample_quantity"],
                )
                if candidate is None:
                    blocked_reason = f"required equipment unavailable: {equipment_type}"
                    break

                equipment, start_time, end_time, duration_minutes, required_batches = candidate
                equipment_id = equipment["id"]
                availability[equipment_id] = end_time
                busy_minutes[equipment_id] += duration_minutes
                previous_end_time = end_time
                start_minute = int((start_time - schedule_origin).total_seconds() // 60)
                end_minute = int((end_time - schedule_origin).total_seconds() // 60)

                steps.append(
                    {
                        "project_id": project["id"],
                        "project_type": project["project_type"],
                        "equipment_type": equipment_type,
                        "equipment_id": equipment_id,
                        "sequence": project["sequence"],
                        "start_minute": start_minute,
                        "start_time": start_time.isoformat(),
                        "duration_minutes": duration_minutes,
                        "end_minute": end_minute,
                        "end_time": end_time.isoformat(),
                        "batch_count": min(equipment["capacity"], order["sample_quantity"]),
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

            promised_finish_time = self._order_promised_finish_time(order)
            sla_status = self._sla_status(previous_end_time, promised_finish_time)
            scheduled_orders.append(
                {
                    **self._serialize_order(order),
                    "status": QueueStatus.SCHEDULED,
                    "steps": steps,
                    "arrival_time": arrival_time.isoformat(),
                    "promised_finish_time": promised_finish_time.isoformat() if promised_finish_time else None,
                    "estimated_finish_minute": int((previous_end_time - schedule_origin).total_seconds() // 60),
                    "estimated_finish_time": previous_end_time.isoformat(),
                    "sla_status": sla_status,
                    "delay_minutes": self._delay_minutes(previous_end_time, promised_finish_time),
                }
            )

        metrics = self._build_metrics(
            scheduled_orders=scheduled_orders,
            blocked_orders=blocked_orders,
            busy_minutes=busy_minutes,
            schedule_origin=schedule_origin,
        )
        self.last_schedule = {
            "scheduled_orders": scheduled_orders,
            "blocked_orders": blocked_orders,
            "equipment_status": self.simulation.equipment_status_summary(),
            "metrics": metrics,
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
            "metrics": self.last_schedule.get("metrics", {}),
        }

    def _select_equipment_instance(
        self,
        equipment_instances: list[dict],
        availability: dict[str, datetime],
        earliest_start: datetime,
        duration_base: int,
        project_type: str,
        duration_is_total: bool,
        sample_quantity: int,
    ):
        candidates = []
        for equipment in equipment_instances:
            equipment_id = equipment["id"]
            capacity = int(equipment["capacity"])
            required_batches = ceil(sample_quantity / capacity)
            duration_minutes = duration_base if duration_is_total else duration_base * required_batches
            start_time = max(earliest_start, availability.get(equipment_id, earliest_start))
            start_time = self._next_slot_start(start_time, duration_minutes, project_type)
            start_time = self._avoid_maintenance(equipment_id, start_time, duration_minutes, project_type)
            end_time = start_time + timedelta(minutes=duration_minutes)
            candidates.append((equipment, start_time, end_time, duration_minutes, required_batches))
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item[2], item[1], item[0]["id"]))

    def _select_next_order(
        self,
        orders: list[dict],
        availability: dict[str, datetime],
        schedule_origin: datetime,
    ) -> dict:
        earliest_by_order = {
            order["id"]: self._earliest_first_step_start(order, availability, schedule_origin)
            for order in orders
        }
        decision_time = min(earliest_by_order.values())
        candidates = [
            order
            for order in orders
            if self._order_release_time(order, schedule_origin) <= decision_time
        ]
        if not candidates:
            candidates = orders
        return min(
            candidates,
            key=lambda order: (
                self.PRIORITY[self._order_type(order["order_type"])],
                max(self._order_release_time(order, schedule_origin), earliest_by_order[order["id"]]),
                self._order_arrival_time(order),
                order["id"],
            ),
        )

    def _earliest_first_step_start(
        self,
        order: dict,
        availability: dict[str, datetime],
        schedule_origin: datetime,
    ) -> datetime:
        arrival_time = self._next_work_start(max(self._order_release_time(order, schedule_origin), schedule_origin))
        flow = self._detection_flow_for_order(order)
        if not flow:
            return arrival_time
        project = flow[0]
        starts = []
        for equipment in self.simulation.equipment_instances_for(project["equipment_type"]):
            capacity = int(equipment["capacity"])
            required_batches = ceil(order["sample_quantity"] / capacity)
            duration_minutes = project["duration_minutes"] if project.get("duration_is_total") else project["duration_minutes"] * required_batches
            candidate = max(arrival_time, availability.get(equipment["id"], arrival_time))
            candidate = self._next_slot_start(candidate, duration_minutes, project["project_type"])
            candidate = self._avoid_maintenance(
                equipment["id"],
                candidate,
                duration_minutes,
                project["project_type"],
            )
            starts.append(candidate)
        return min(starts) if starts else arrival_time

    def _detection_flow_for_order(self, order: dict) -> list[dict]:
        route = order.get("detection_route") or []
        if route:
            normalized = []
            for step in route:
                normalized.append(
                    {
                        "id": step.get("id") or step.get("project_id"),
                        "project_type": step["project_type"],
                        "equipment_type": step["equipment_type"],
                        "sequence": step["sequence"],
                        "duration_minutes": step["duration_minutes"],
                        "duration_is_total": True,
                        "duration_profile": step.get("duration_profile", {}),
                        "staff_role": step.get("staff_role"),
                    }
                )
            return sorted(normalized, key=lambda item: item["sequence"])
        return self.simulation.get_detection_flow(
            order["certification_type"],
            order.get("requested_projects") or [],
        )

    def _avoid_maintenance(self, equipment_id: str, start_time: datetime, duration_minutes: int, project_type: str) -> datetime:
        current = start_time
        duration = timedelta(minutes=duration_minutes)
        changed = True
        while changed:
            changed = False
            for window in self.simulation.maintenance_windows_for(equipment_id):
                if current < window["end_dt"] and current + duration > window["start_dt"]:
                    current = self._next_slot_start(window["end_dt"], duration_minutes, project_type)
                    changed = True
                    break
        return current

    def _next_slot_start(self, value: datetime, duration_minutes: int, project_type: str) -> datetime:
        current = self._next_work_start(value)
        duration = timedelta(minutes=duration_minutes)
        while True:
            day_end = datetime.combine(current.date(), time(18, 0), tzinfo=current.tzinfo)
            if current + duration > day_end:
                current = self._next_work_start(
                    datetime.combine(current.date() + timedelta(days=1), time(9, 0), tzinfo=current.tzinfo)
                )
                continue

            lunch_start = datetime.combine(current.date(), time(12, 0), tzinfo=current.tzinfo)
            lunch_end = datetime.combine(current.date(), time(13, 0), tzinfo=current.tzinfo)
            can_continue_during_lunch = project_type == "environmental_check"
            if not can_continue_during_lunch and current < lunch_end and current + duration > lunch_start:
                current = lunch_end
                continue

            return current

    def _next_work_start(self, value: datetime) -> datetime:
        current = self._ensure_tz(value)
        while current.weekday() >= 5:
            current = datetime.combine(current.date() + timedelta(days=1), time(9, 0), tzinfo=current.tzinfo)
        day_start = datetime.combine(current.date(), time(9, 0), tzinfo=current.tzinfo)
        day_end = datetime.combine(current.date(), time(18, 0), tzinfo=current.tzinfo)
        if current < day_start:
            return day_start
        if current >= day_end:
            return self._next_work_start(datetime.combine(current.date() + timedelta(days=1), time(9, 0), tzinfo=current.tzinfo))
        return current

    def _schedule_origin(self, orders: list[dict]) -> datetime:
        if not orders:
            return self._next_work_start(datetime.now(self.DEFAULT_TZ))
        return self._next_work_start(min(self._order_arrival_time(order) for order in orders))

    def _order_arrival_time(self, order: dict) -> datetime:
        value = order.get("arrival_time") or order.get("created_at")
        return self._parse_datetime(value)

    def _order_release_time(self, order: dict, schedule_origin: datetime) -> datetime:
        if order.get("arrival_time"):
            return self._order_arrival_time(order)
        return schedule_origin

    def _order_promised_finish_time(self, order: dict) -> datetime | None:
        value = order.get("promised_finish_time")
        return self._parse_datetime(value) if value else None

    def _parse_datetime(self, value) -> datetime:
        if isinstance(value, datetime):
            return self._ensure_tz(value)
        if isinstance(value, str):
            return self._ensure_tz(datetime.fromisoformat(value))
        return datetime.now(self.DEFAULT_TZ)

    def _ensure_tz(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=self.DEFAULT_TZ)
        return value

    def _sla_status(self, finish_time: datetime, promised_finish_time: datetime | None) -> str:
        if promised_finish_time is None:
            return "not_applicable"
        return "on_time" if finish_time <= promised_finish_time else "delayed"

    def _delay_minutes(self, finish_time: datetime, promised_finish_time: datetime | None) -> int:
        if promised_finish_time is None or finish_time <= promised_finish_time:
            return 0
        return int((finish_time - promised_finish_time).total_seconds() // 60)

    def _build_metrics(
        self,
        scheduled_orders: list[dict],
        blocked_orders: list[dict],
        busy_minutes: Counter[str],
        schedule_origin: datetime,
    ) -> dict:
        waits = []
        for order in scheduled_orders:
            if not order.get("steps"):
                continue
            first_start = self._parse_datetime(order["steps"][0]["start_time"])
            arrival = self._parse_datetime(order["arrival_time"])
            waits.append(max(0, int((first_start - arrival).total_seconds() // 60)))
        finish_times = [
            self._parse_datetime(order["estimated_finish_time"])
            for order in scheduled_orders
            if order.get("estimated_finish_time")
        ]
        horizon_minutes = max(
            1,
            int(((max(finish_times) if finish_times else schedule_origin) - schedule_origin).total_seconds() // 60),
        )
        equipment_utilization = {
            equipment_id: round(minutes / horizon_minutes, 4)
            for equipment_id, minutes in sorted(busy_minutes.items())
        }
        vip_orders = [order for order in scheduled_orders if order["order_type"] == "vip" and order.get("promised_finish_time")]
        urgent_orders = [order for order in scheduled_orders if order["order_type"] == "urgent" and order.get("promised_finish_time")]
        blocked_reasons = Counter(order.get("reason", "unknown") for order in blocked_orders)
        return {
            "scheduled_count": len(scheduled_orders),
            "blocked_count": len(blocked_orders),
            "average_wait_minutes": round(sum(waits) / len(waits), 2) if waits else 0.0,
            "equipment_utilization": equipment_utilization,
            "vip_sla_rate": self._sla_rate(vip_orders),
            "urgent_delay_rate": self._delay_rate(urgent_orders),
            "blocked_reason_distribution": dict(blocked_reasons),
        }

    def _sla_rate(self, orders: list[dict]) -> float:
        if not orders:
            return 1.0
        return round(sum(1 for order in orders if order.get("sla_status") == "on_time") / len(orders), 4)

    def _delay_rate(self, orders: list[dict]) -> float:
        if not orders:
            return 0.0
        return round(sum(1 for order in orders if order.get("sla_status") == "delayed") / len(orders), 4)

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
