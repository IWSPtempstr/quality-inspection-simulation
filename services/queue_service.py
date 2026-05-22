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

    def rebuild_schedule(self, orders: Iterable[dict], strategy: str = "hybrid_weighted") -> dict:
        self.simulation.reset_runtime_state()
        active_orders = [
            order
            for order in orders
            if self._enum_value(order.get("status", QueueStatus.PENDING)) != QueueStatus.CANCELLED.value
        ]
        schedule_origin = self._schedule_origin(active_orders)
        availability: dict[str, datetime] = {
            item["id"]: schedule_origin
            for item in self.simulation.list_equipment()
            if self._enum_value(item["status"]) != "offline"
        }
        resource_availability = self._initial_resource_availability(schedule_origin)
        employee_assignments: dict[str, list[dict]] = {
            employee["employee_id"]: [] for employee in self.simulation.employee_instances()
        }
        consumable_usage: Counter[tuple[str, str]] = Counter()
        busy_minutes: Counter[str] = Counter()
        scheduled_orders: list[dict] = []
        blocked_orders: list[dict] = []

        unscheduled_orders = list(active_orders)
        while unscheduled_orders:
            order = self._select_next_order(unscheduled_orders, availability, schedule_origin, strategy)
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
            previous_lab_area: str | None = None
            previous_lab_area_explicit = False
            steps: list[dict] = []
            blocked_reason = ""

            preprocessing = order.get("preprocessing_profile")
            if preprocessing:
                prep_step = self._schedule_support_step(
                    order=order,
                    step_kind="preprocessing",
                    project_type="preprocessing",
                    earliest_start=previous_end_time,
                    duration_minutes=int(preprocessing["required_minutes"]),
                    lab_area=preprocessing.get("lab_area", "intake"),
                    required_roles=preprocessing.get("required_roles", ["sample_operator"]),
                    required_operator_count=int(preprocessing.get("required_operator_count", 1)),
                    resource_bucket="preprocessing_resources",
                    resource_type=preprocessing.get("resource_type", "prep_station"),
                    employee_assignments=employee_assignments,
                    resource_availability=resource_availability,
                    schedule_origin=schedule_origin,
                    sequence=0,
                )
                if prep_step is None:
                    blocked_reason = "preprocessing resource or personnel unavailable"
                else:
                    steps.append(prep_step)
                    previous_end_time = self._parse_datetime(prep_step["end_time"])
                    previous_lab_area = prep_step["lab_area"]
                    previous_lab_area_explicit = True

            if blocked_reason:
                blocked_orders.append({**self._serialize_order(order), "status": QueueStatus.BLOCKED, "reason": blocked_reason})
                continue

            for project in flow:
                lab_area = self._project_lab_area(project)
                lab_area_explicit = bool(project.get("lab_area_explicit"))
                if previous_lab_area and previous_lab_area != lab_area and previous_lab_area_explicit and lab_area_explicit:
                    transfer_rule = self.simulation.transfer_rule(previous_lab_area, lab_area)
                    if transfer_rule:
                        transfer_step = self._schedule_support_step(
                            order=order,
                            step_kind="transfer",
                            project_type="sample_transfer",
                            earliest_start=previous_end_time,
                            duration_minutes=int(transfer_rule.get("duration_minutes", 10)),
                            lab_area=lab_area,
                            required_roles=transfer_rule.get("required_roles", ["transfer_operator"]),
                            required_operator_count=int(transfer_rule.get("required_operator_count", 1)),
                            resource_bucket="transfer_resources",
                            resource_type=transfer_rule.get("resource_type", "transfer_cart"),
                            employee_assignments=employee_assignments,
                            resource_availability=resource_availability,
                            schedule_origin=schedule_origin,
                            sequence=int(project["sequence"]),
                            constraint_detail={"from_lab_area": previous_lab_area, "to_lab_area": lab_area},
                        )
                        if transfer_step is None:
                            blocked_reason = f"transfer resource or personnel unavailable: {previous_lab_area}->{lab_area}"
                            break
                        steps.append(transfer_step)
                        previous_end_time = self._parse_datetime(transfer_step["end_time"])

                candidate = self._select_detection_candidate(
                    order=order,
                    project={**project, "lab_area": lab_area},
                    availability=availability,
                    earliest_start=previous_end_time,
                    employee_assignments=employee_assignments,
                    consumable_usage=consumable_usage,
                    schedule_origin=schedule_origin,
                )
                if candidate is None:
                    blocked_reason = f"required equipment, personnel or consumable unavailable: {project['equipment_type']}"
                    break

                step = candidate["step"]
                equipment_id = step["equipment_id"]
                availability[equipment_id] = self._parse_datetime(step["end_time"])
                busy_minutes[equipment_id] += int(step["duration_minutes"])
                self._commit_employee_assignments(
                    employee_assignments=employee_assignments,
                    employee_ids=step["assigned_employee_ids"],
                    start_time=self._parse_datetime(step["staff_start_time"]),
                    end_time=self._parse_datetime(step["staff_end_time"]),
                    lab_area=lab_area,
                    project_type=project["project_type"],
                    equipment_type=project["equipment_type"],
                    mode=step["constraint_detail"]["operator_requirements"]["supervision_mode"],
                )
                self._commit_consumables(consumable_usage, step)
                previous_end_time = self._parse_datetime(step["end_time"])
                previous_lab_area = lab_area
                previous_lab_area_explicit = lab_area_explicit
                steps.append({key: value for key, value in step.items() if key not in {"staff_start_time", "staff_end_time"}})

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
            strategy=strategy,
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

    def _select_detection_candidate(
        self,
        order: dict,
        project: dict,
        availability: dict[str, datetime],
        earliest_start: datetime,
        employee_assignments: dict[str, list[dict]],
        consumable_usage: Counter[tuple[str, str]],
        schedule_origin: datetime,
    ) -> dict | None:
        equipment_instances = self.simulation.equipment_instances_for(project["equipment_type"])
        if not equipment_instances:
            return None

        candidates = []
        for equipment in equipment_instances:
            candidate = self._candidate_for_equipment(
                order=order,
                project=project,
                equipment=equipment,
                equipment_available_at=availability.get(equipment["id"], earliest_start),
                earliest_start=earliest_start,
                employee_assignments=employee_assignments,
                consumable_usage=consumable_usage,
                schedule_origin=schedule_origin,
            )
            if candidate:
                candidates.append(candidate)
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (
                self._parse_datetime(item["step"]["end_time"]),
                self._parse_datetime(item["step"]["start_time"]),
                item["step"]["equipment_id"],
            ),
        )

    def _candidate_for_equipment(
        self,
        order: dict,
        project: dict,
        equipment: dict,
        equipment_available_at: datetime,
        earliest_start: datetime,
        employee_assignments: dict[str, list[dict]],
        consumable_usage: Counter[tuple[str, str]],
        schedule_origin: datetime,
    ) -> dict | None:
        capacity = int(equipment["capacity"])
        required_batches = ceil(int(order["sample_quantity"]) / capacity)
        duration_base = int(project["duration_minutes"])
        duration_is_total = bool(project.get("duration_is_total"))
        detection_minutes = duration_base if duration_is_total else duration_base * required_batches
        setup_minutes = int(project.get("setup_minutes", 0)) if duration_is_total else 0
        duration_minutes = detection_minutes + setup_minutes
        consumable_units = int(project.get("consumable_units_per_batch", 0) or 0) * required_batches
        consumable_capacity = self.simulation.consumable_capacity(project.get("consumable_type"))
        if consumable_capacity is not None and consumable_units > consumable_capacity:
            return None

        current = max(earliest_start, equipment_available_at)
        for _ in range(1000):
            start_time = self._next_slot_start(current, duration_minutes, project["project_type"])
            start_time = self._avoid_maintenance(equipment["id"], start_time, duration_minutes, project["project_type"])
            start_time = self._apply_consumable_window(
                start_time=start_time,
                duration_minutes=duration_minutes,
                project_type=project["project_type"],
                consumable_type=project.get("consumable_type"),
                consumable_units=consumable_units,
                consumable_usage=consumable_usage,
            )
            end_time = start_time + timedelta(minutes=duration_minutes)
            staff_start, staff_end = self._staff_interval(start_time, end_time, project)
            employee_ids = self._find_employee_assignment(
                project=project,
                start_time=staff_start,
                end_time=staff_end,
                employee_assignments=employee_assignments,
            )
            if employee_ids:
                return {
                    "step": {
                        "step_kind": "detection",
                        "project_id": project["id"],
                        "project_type": project["project_type"],
                        "equipment_type": project["equipment_type"],
                        "equipment_id": equipment["id"],
                        "lab_area": project["lab_area"],
                        "assigned_employee_ids": employee_ids,
                        "resource_ids": [],
                        "constraint_detail": {
                            "operator_requirements": self._operator_requirements(project),
                            "consumable_checked": bool(project.get("consumable_type")),
                        },
                        "setup_minutes": setup_minutes,
                        "staff_role": project.get("staff_role"),
                        "consumable_type": project.get("consumable_type"),
                        "consumable_units": consumable_units,
                        "sequence": project["sequence"],
                        "start_minute": int((start_time - schedule_origin).total_seconds() // 60),
                        "start_time": start_time.isoformat(),
                        "duration_minutes": duration_minutes,
                        "end_minute": int((end_time - schedule_origin).total_seconds() // 60),
                        "end_time": end_time.isoformat(),
                        "batch_count": min(capacity, int(order["sample_quantity"])),
                        "required_batches": required_batches,
                        "staff_start_time": staff_start.isoformat(),
                        "staff_end_time": staff_end.isoformat(),
                    }
                }
            next_release = self._next_employee_release(project, staff_start, employee_assignments)
            if next_release is None:
                return None
            current = max(next_release, start_time + timedelta(minutes=1))
        return None

    def _schedule_support_step(
        self,
        order: dict,
        step_kind: str,
        project_type: str,
        earliest_start: datetime,
        duration_minutes: int,
        lab_area: str,
        required_roles: list[str],
        required_operator_count: int,
        resource_bucket: str,
        resource_type: str,
        employee_assignments: dict[str, list[dict]],
        resource_availability: dict[str, datetime],
        schedule_origin: datetime,
        sequence: int,
        constraint_detail: dict | None = None,
    ) -> dict | None:
        resources = self.simulation.resources_for(resource_bucket, resource_type)
        if not resources:
            return None
        current = earliest_start
        synthetic_project = {
            "project_type": project_type,
            "equipment_type": resource_type,
            "lab_area": lab_area,
            "operator_requirements": {
                "required_operator_count": required_operator_count,
                "required_roles": required_roles,
                "supervision_mode": "exclusive",
                "staff_phase": "full",
            },
        }
        for _ in range(1000):
            resource = min(resources, key=lambda item: resource_availability.get(item["resource_id"], earliest_start))
            start_time = max(current, resource_availability.get(resource["resource_id"], earliest_start))
            start_time = self._next_slot_start(start_time, duration_minutes, project_type)
            end_time = start_time + timedelta(minutes=duration_minutes)
            employee_ids = self._find_employee_assignment(
                project=synthetic_project,
                start_time=start_time,
                end_time=end_time,
                employee_assignments=employee_assignments,
            )
            if employee_ids:
                resource_availability[resource["resource_id"]] = end_time
                self._commit_employee_assignments(
                    employee_assignments=employee_assignments,
                    employee_ids=employee_ids,
                    start_time=start_time,
                    end_time=end_time,
                    lab_area=lab_area,
                    project_type=project_type,
                    equipment_type=resource_type,
                    mode="exclusive",
                )
                detail = {
                    "operator_requirements": synthetic_project["operator_requirements"],
                    "resource_type": resource_type,
                    **(constraint_detail or {}),
                }
                return {
                    "step_kind": step_kind,
                    "project_id": None,
                    "project_type": project_type,
                    "equipment_type": None,
                    "equipment_id": None,
                    "lab_area": lab_area,
                    "assigned_employee_ids": employee_ids,
                    "resource_ids": [resource["resource_id"]],
                    "constraint_detail": detail,
                    "setup_minutes": 0,
                    "staff_role": required_roles[0] if required_roles else None,
                    "consumable_type": None,
                    "consumable_units": 0,
                    "sequence": sequence,
                    "start_minute": int((start_time - schedule_origin).total_seconds() // 60),
                    "start_time": start_time.isoformat(),
                    "duration_minutes": duration_minutes,
                    "end_minute": int((end_time - schedule_origin).total_seconds() // 60),
                    "end_time": end_time.isoformat(),
                    "batch_count": None,
                    "required_batches": None,
                }
            next_release = self._next_employee_release(synthetic_project, start_time, employee_assignments)
            if next_release is None:
                return None
            current = max(next_release, start_time + timedelta(minutes=1))
        return None

    def _find_employee_assignment(
        self,
        project: dict,
        start_time: datetime,
        end_time: datetime,
        employee_assignments: dict[str, list[dict]],
    ) -> list[str] | None:
        requirements = self._operator_requirements(project)
        required_count = int(requirements["required_operator_count"])
        required_roles = list(requirements.get("required_roles") or [])
        mode = requirements.get("supervision_mode", "shared_supervision")
        candidates = [
            employee
            for employee in self.simulation.employee_instances()
            if self._employee_matches(employee, project, required_roles)
            and self._employee_available(employee, start_time, end_time, project["lab_area"], mode, employee_assignments)
        ]
        if len(candidates) < required_count:
            return None

        selected: list[dict] = []
        for role in required_roles:
            match = next(
                (
                    employee
                    for employee in candidates
                    if employee not in selected and role in employee.get("roles", [])
                ),
                None,
            )
            if match:
                selected.append(match)
            if len(selected) >= required_count:
                break
        for employee in candidates:
            if len(selected) >= required_count:
                break
            if employee not in selected:
                selected.append(employee)

        if len(selected) < required_count:
            return None
        return [employee["employee_id"] for employee in selected[:required_count]]

    def _employee_matches(self, employee: dict, project: dict, required_roles: list[str]) -> bool:
        if project["lab_area"] not in employee.get("lab_areas", []):
            return False
        roles = set(employee.get("roles", []))
        skills = set(employee.get("skills", []))
        if required_roles and not roles.intersection(required_roles):
            return False
        return bool(
            skills.intersection({project.get("project_type"), project.get("equipment_type")})
            or roles.intersection(required_roles)
            or not required_roles
        )

    def _employee_available(
        self,
        employee: dict,
        start_time: datetime,
        end_time: datetime,
        lab_area: str,
        mode: str,
        employee_assignments: dict[str, list[dict]],
    ) -> bool:
        overlapping = [
            assignment
            for assignment in employee_assignments.get(employee["employee_id"], [])
            if start_time < assignment["end_time"] and end_time > assignment["start_time"]
        ]
        if not overlapping:
            return True
        if mode != "shared_supervision":
            return False
        if any(assignment["mode"] != "shared_supervision" for assignment in overlapping):
            return False
        if any(assignment["lab_area"] != lab_area for assignment in overlapping):
            return False
        max_parallel = int(employee.get("max_parallel_assignments", 1))
        return len(overlapping) + 1 <= max_parallel

    def _next_employee_release(
        self,
        project: dict,
        start_time: datetime,
        employee_assignments: dict[str, list[dict]],
    ) -> datetime | None:
        requirements = self._operator_requirements(project)
        matching_employees = [
            employee
            for employee in self.simulation.employee_instances()
            if self._employee_matches(employee, project, requirements.get("required_roles", []))
        ]
        if not matching_employees:
            return None
        releases = [
            assignment["end_time"]
            for employee in matching_employees
            for assignment in employee_assignments.get(employee["employee_id"], [])
            if assignment["end_time"] > start_time
        ]
        if not releases:
            return start_time + timedelta(minutes=5)
        return min(releases)

    def _commit_employee_assignments(
        self,
        employee_assignments: dict[str, list[dict]],
        employee_ids: list[str],
        start_time: datetime,
        end_time: datetime,
        lab_area: str,
        project_type: str,
        equipment_type: str,
        mode: str,
    ) -> None:
        for employee_id in employee_ids:
            employee_assignments.setdefault(employee_id, []).append(
                {
                    "start_time": start_time,
                    "end_time": end_time,
                    "lab_area": lab_area,
                    "project_type": project_type,
                    "equipment_type": equipment_type,
                    "mode": mode,
                }
            )

    def _staff_interval(self, start_time: datetime, end_time: datetime, project: dict) -> tuple[datetime, datetime]:
        requirements = self._operator_requirements(project)
        if requirements.get("staff_phase") == "setup":
            setup_minutes = int(project.get("setup_minutes", 0))
            if setup_minutes > 0:
                return start_time, min(end_time, start_time + timedelta(minutes=setup_minutes))
        return start_time, end_time

    def _operator_requirements(self, project: dict) -> dict:
        raw = project.get("operator_requirements") or {}
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(mode="json")
        roles = list(raw.get("required_roles") or [])
        if not roles and project.get("staff_role"):
            roles = [project["staff_role"]]
        return {
            "required_operator_count": int(raw.get("required_operator_count", 1)),
            "required_roles": roles,
            "supervision_mode": raw.get("supervision_mode", "shared_supervision"),
            "staff_phase": raw.get("staff_phase", "running"),
        }

    def _initial_resource_availability(self, schedule_origin: datetime) -> dict[str, datetime]:
        resource_ids = [
            resource["resource_id"]
            for bucket in ("preprocessing_resources", "transfer_resources")
            for resource in self.simulation.resources_for(bucket)
        ]
        return {resource_id: schedule_origin for resource_id in resource_ids}

    def _apply_consumable_window(
        self,
        start_time: datetime,
        duration_minutes: int,
        project_type: str,
        consumable_type: str | None,
        consumable_units: int,
        consumable_usage: Counter[tuple[str, str]],
    ) -> datetime:
        capacity = self.simulation.consumable_capacity(consumable_type)
        if not consumable_type or capacity is None or consumable_units <= 0:
            return start_time
        current = start_time
        while consumable_usage[(current.date().isoformat(), consumable_type)] + consumable_units > capacity:
            current = self._next_slot_start(
                datetime.combine(current.date() + timedelta(days=1), time(9, 0), tzinfo=current.tzinfo),
                duration_minutes,
                project_type,
            )
        return current

    def _commit_consumables(self, consumable_usage: Counter[tuple[str, str]], step: dict) -> None:
        consumable_type = step.get("consumable_type")
        consumable_units = int(step.get("consumable_units") or 0)
        if consumable_type and consumable_units:
            start = self._parse_datetime(step["start_time"])
            consumable_usage[(start.date().isoformat(), consumable_type)] += consumable_units

    def _project_lab_area(self, project: dict) -> str:
        lab_area = project.get("lab_area")
        if lab_area and lab_area != "lab":
            return lab_area
        for equipment in self.simulation.list_equipment():
            if equipment["equipment_type"] == project["equipment_type"]:
                return equipment.get("lab_area") or "lab"
        return "lab"

    def _select_next_order(
        self,
        orders: list[dict],
        availability: dict[str, datetime],
        schedule_origin: datetime,
        strategy: str,
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
        return min(candidates, key=lambda order: self._strategy_key(order, strategy, earliest_by_order, availability, schedule_origin))

    def _strategy_key(
        self,
        order: dict,
        strategy: str,
        earliest_by_order: dict[str, datetime],
        availability: dict[str, datetime],
        schedule_origin: datetime,
    ):
        priority = self.PRIORITY[self._order_type(order["order_type"])]
        earliest_ready = max(self._order_release_time(order, schedule_origin), earliest_by_order[order["id"]])
        arrival = self._order_arrival_time(order)
        promised = self._order_promised_finish_time(order) or datetime.max.replace(tzinfo=arrival.tzinfo)
        duration = self._estimate_order_duration(order)
        bottleneck = self._resource_scarcity_score(order)
        if strategy == "earliest_due_date":
            return (promised, priority, earliest_ready, arrival, order["id"])
        if strategy == "shortest_processing_time":
            return (duration, priority, promised, earliest_ready, arrival, order["id"])
        if strategy == "bottleneck_resource_first":
            return (-bottleneck, priority, promised, earliest_ready, arrival, order["id"])
        if strategy == "hybrid_weighted":
            due_minutes = max(0, int((promised - schedule_origin).total_seconds() // 60)) if promised.year < 9000 else 10**9
            weighted = priority * 1_000_000 + due_minutes * 10 + bottleneck * 1_000
            return (weighted, earliest_ready, arrival, order["id"], duration)
        return (
            priority,
            earliest_ready,
            arrival,
            order["id"],
        )

    def _estimate_order_duration(self, order: dict) -> int:
        total = 0
        for project in self._detection_flow_for_order(order):
            capacity = max(1, self.simulation.equipment_capacity(project["equipment_type"]))
            required_batches = ceil(int(order["sample_quantity"]) / capacity)
            duration = int(project["duration_minutes"])
            if not project.get("duration_is_total"):
                duration *= required_batches
            duration += int(project.get("setup_minutes", 0) or 0) if project.get("duration_is_total") else 0
            total += duration
        preprocessing = order.get("preprocessing_profile")
        if preprocessing:
            total += int(preprocessing.get("required_minutes", 0) or 0)
        return total

    def _resource_scarcity_score(self, order: dict) -> float:
        scores = []
        for project in self._detection_flow_for_order(order):
            equipment_count = len(self.simulation.equipment_instances_for(project["equipment_type"]))
            scores.append(1 / max(1, equipment_count))
        return max(scores) if scores else 1.0

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
            required_batches = ceil(int(order["sample_quantity"]) / capacity)
            duration_minutes = project["duration_minutes"] if project.get("duration_is_total") else project["duration_minutes"] * required_batches
            duration_minutes += int(project.get("setup_minutes", 0)) if project.get("duration_is_total") else 0
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
                        "lab_area": step.get("lab_area", "lab"),
                        "lab_area_explicit": bool(step.get("lab_area")),
                        "sequence": step["sequence"],
                        "duration_minutes": step["duration_minutes"],
                        "duration_is_total": True,
                        "setup_minutes": int(step.get("setup_minutes", 0) or 0),
                        "duration_profile": step.get("duration_profile", {}),
                        "staff_role": step.get("staff_role"),
                        "operator_requirements": step.get("operator_requirements", {}),
                        "consumable_type": step.get("consumable_type"),
                        "consumable_units_per_batch": int(step.get("consumable_units_per_batch", 0) or 0),
                    }
                )
            return sorted(normalized, key=lambda item: item["sequence"])
        return [
            {**project, "setup_minutes": 0, "duration_is_total": False, "lab_area_explicit": False}
            for project in self.simulation.get_detection_flow(
                order["certification_type"],
                order.get("requested_projects") or [],
            )
        ]

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
        strategy: str,
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
        normal_orders = [order for order in scheduled_orders if order["order_type"] == "normal" and order.get("promised_finish_time")]
        blocked_reasons = Counter(order.get("reason", "unknown") for order in blocked_orders)
        total_delay_minutes = sum(int(order.get("delay_minutes") or 0) for order in scheduled_orders)
        vip_delay_minutes = sum(int(order.get("delay_minutes") or 0) for order in vip_orders)
        urgent_delay_minutes = sum(int(order.get("delay_minutes") or 0) for order in urgent_orders)
        normal_delay_minutes = sum(int(order.get("delay_minutes") or 0) for order in normal_orders)
        promised_orders = [order for order in scheduled_orders if order.get("promised_finish_time")]
        total_equipment_count = max(
            1,
            len([item for item in self.simulation.list_equipment() if self._enum_value(item["status"]) != "offline"]),
        )
        equipment_idle_penalty = max(0, horizon_minutes * total_equipment_count - sum(busy_minutes.values()))
        personnel_blocked_count = sum(1 for order in blocked_orders if "personnel" in order.get("reason", ""))
        transfer_wait_minutes = sum(
            int(step.get("duration_minutes") or 0)
            for order in scheduled_orders
            for step in order.get("steps", [])
            if step.get("step_kind") == "transfer"
        )
        return {
            "scheduled_count": len(scheduled_orders),
            "blocked_count": len(blocked_orders),
            "average_wait_minutes": round(sum(waits) / len(waits), 2) if waits else 0.0,
            "equipment_utilization": equipment_utilization,
            "vip_sla_rate": self._sla_rate(vip_orders),
            "urgent_delay_rate": self._delay_rate(urgent_orders),
            "blocked_reason_distribution": dict(blocked_reasons),
            "total_delay_minutes": total_delay_minutes,
            "vip_delay_minutes": vip_delay_minutes,
            "urgent_delay_minutes": urgent_delay_minutes,
            "normal_delay_minutes": normal_delay_minutes,
            "on_time_rate": self._sla_rate(promised_orders),
            "equipment_idle_penalty": equipment_idle_penalty,
            "personnel_blocked_count": personnel_blocked_count,
            "transfer_wait_minutes": transfer_wait_minutes,
            "selected_strategy": strategy,
            "candidate_scores": {strategy: 0.0},
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
