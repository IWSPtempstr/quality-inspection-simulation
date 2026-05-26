from __future__ import annotations

import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from math import ceil
from typing import Any

from ortools.sat.python import cp_model

from domain.schemas import QueueStatus


class CpSatScheduleService:
    """Build a rolling-window CP-SAT schedule and fall back to rule scheduling when unsupported."""

    DEFAULT_FALLBACK_STRATEGY = "sla_guarded_hybrid"

    def __init__(self, queue_service) -> None:
        self.queue_service = queue_service
        self.time_limit_seconds = float(os.getenv("CP_SAT_TIME_LIMIT_SECONDS", "10"))
        self.num_workers = int(os.getenv("CP_SAT_NUM_WORKERS", "4"))

    def solve(
        self,
        orders: list[dict[str, Any]],
        schedule_origin: datetime,
        forecast_orders: list[dict[str, Any]] | None = None,
        locked_steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        reason = self._unsupported_reason(orders)
        if reason:
            return self._fallback(orders, reason, started_at, forecast_orders or [])

        external_forecast_orders = forecast_orders or []
        try:
            solve_orders, capped_forecast_orders = self._cap_active_orders(orders, schedule_origin)
            result = self._solve_supported(
                solve_orders,
                orders,
                schedule_origin,
                [*external_forecast_orders, *capped_forecast_orders],
                external_forecast_orders,
                locked_steps or [],
                started_at,
            )
        except Exception as exc:  # noqa: BLE001
            return self._fallback(orders, f"cp_sat_exception: {exc}", started_at, external_forecast_orders)
        return result

    def _unsupported_reason(self, orders: list[dict[str, Any]]) -> str | None:
        for order in orders:
            flow = self.queue_service._detection_flow_for_order(order)
            if not flow:
                return f"no_detection_flow:{order.get('id')}"
            for project in flow:
                if not self.queue_service.simulation.equipment_instances_for(project["equipment_type"]):
                    return f"no_equipment:{project['equipment_type']}"
        return None

    def _cap_active_orders(
        self,
        orders: list[dict[str, Any]],
        schedule_origin: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        max_orders = int(os.getenv("CP_SAT_MAX_ACTIVE_ORDERS", "80"))
        if max_orders <= 0 or len(orders) <= max_orders:
            return orders, []
        ordered = sorted(
            orders,
            key=lambda order: (
                self.queue_service.PRIORITY[self.queue_service._order_type(order["order_type"])],
                self.queue_service._order_promised_finish_time(order) or datetime.max.replace(tzinfo=schedule_origin.tzinfo),
                self.queue_service._order_release_time(order, schedule_origin),
                order.get("id", ""),
            ),
        )
        return ordered[:max_orders], [self.queue_service._serialize_order(order) for order in ordered[max_orders:]]

    def _solve_supported(
        self,
        orders: list[dict[str, Any]],
        fallback_orders: list[dict[str, Any]],
        schedule_origin: datetime,
        forecast_orders: list[dict[str, Any]],
        fallback_forecast_orders: list[dict[str, Any]],
        locked_steps: list[dict[str, Any]],
        started_at: float,
    ) -> dict[str, Any]:
        model = cp_model.CpModel()
        horizon = self._horizon_minutes(orders, schedule_origin)
        resource_intervals: dict[str, list[Any]] = defaultdict(list)
        consumable_windows: dict[str, dict[str, Any]] = {}
        staff_intervals: dict[str, list[Any]] = defaultdict(list)
        task_records: list[dict[str, Any]] = []
        delay_vars = []
        priority_weight = {"vip": 1_000_000, "urgent": 250_000, "normal": 25_000}

        self._add_locked_intervals(model, locked_steps, schedule_origin, horizon, resource_intervals, staff_intervals)
        for order in orders:
            previous_end = None
            release_seconds = (self.queue_service._order_release_time(order, schedule_origin) - schedule_origin).total_seconds()
            release_minute = max(0, int(ceil(release_seconds / 60)))
            task_specs = self._expand_order_tasks(order)
            for index, task in enumerate(task_specs):
                start = model.NewIntVar(release_minute, horizon, f"{order['id']}_{index}_start")
                end = model.NewIntVar(release_minute, horizon, f"{order['id']}_{index}_end")
                if previous_end is not None:
                    model.Add(start >= previous_end)

                alternatives = self._resource_alternatives(order, task)
                if not alternatives:
                    return self._fallback(fallback_orders, f"no_resource:{task['project_type']}", started_at, fallback_forecast_orders)
                model_alternatives = []
                for alternative in alternatives:
                    duration = int(alternative["duration"])
                    present = model.NewBoolVar(f"{order['id']}_{index}_{alternative['resource_id']}_present")
                    interval = model.NewOptionalIntervalVar(
                        start,
                        duration,
                        end,
                        present,
                        f"{order['id']}_{index}_{alternative['resource_id']}_interval",
                    )
                    self._add_calendar_constraint(
                        model=model,
                        start=start,
                        duration=duration,
                        present=present,
                        task=task,
                        schedule_origin=schedule_origin,
                        horizon=horizon,
                    )
                    resource_intervals[alternative["resource_id"]].append(interval)
                    model_alternatives.append({**alternative, "present": present, "interval": interval})
                model.AddExactlyOne(item["present"] for item in model_alternatives)

                staff_assignments = self._add_staff_constraints(
                    model=model,
                    order=order,
                    task=task,
                    task_index=index,
                    start=start,
                    end=end,
                    horizon=horizon,
                    staff_intervals=staff_intervals,
                )
                self._add_consumable_constraint(
                    model=model,
                    order=order,
                    task=task,
                    task_index=index,
                    start=start,
                    horizon=horizon,
                    consumable_windows=consumable_windows,
                )
                task_records.append(
                    {
                        "order": order,
                        "task": task,
                        "sequence_index": index,
                        "start": start,
                        "end": end,
                        "alternatives": model_alternatives,
                        "staff_assignments": staff_assignments,
                    }
                )
                previous_end = end
            if previous_end is not None:
                promised = self.queue_service._order_promised_finish_time(order)
                if promised:
                    due = max(0, int((promised - schedule_origin).total_seconds() // 60))
                    delay = model.NewIntVar(0, horizon, f"{order['id']}_delay")
                    model.Add(delay >= previous_end - due)
                    model.Add(delay >= 0)
                    order_type = self.queue_service._enum_value(order["order_type"])
                    delay_vars.append(delay * priority_weight.get(order_type, 25_000))
                order_type = self.queue_service._enum_value(order["order_type"])
                delay_vars.append(previous_end * {"vip": 10, "urgent": 5, "normal": 1}.get(order_type, 1))

        for intervals in resource_intervals.values():
            model.AddNoOverlap(intervals)
        for window in consumable_windows.values():
            model.AddCumulative(window["intervals"], window["demands"], window["capacity"])
        for intervals in staff_intervals.values():
            model.AddNoOverlap(intervals)
        model.Minimize(sum(delay_vars) if delay_vars else 0)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit_seconds
        solver.parameters.num_search_workers = self.num_workers
        status = solver.Solve(model)
        status_name = self._status_name(status)
        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            return self._fallback(fallback_orders, f"cp_sat_{status_name}", started_at, fallback_forecast_orders)

        scheduled_orders, busy_minutes = self._build_schedule_from_solution(
            orders=orders,
            task_records=task_records,
            solver=solver,
            schedule_origin=schedule_origin,
        )
        metrics = self.queue_service._build_metrics(
            scheduled_orders=scheduled_orders,
            blocked_orders=[],
            busy_minutes=busy_minutes,
            schedule_origin=schedule_origin,
            strategy="cp_sat_rolling",
        )
        metrics.update(
            {
                "solver_used": "cp_sat",
                "solver_status": status_name,
                "solver_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "fallback_used": False,
                "fallback_reason": None,
                "forecast_count": len(forecast_orders),
                "locked_step_count": len(locked_steps),
                "cp_sat_v2_support_steps": True,
            }
        )
        self.queue_service.last_schedule = {
            "scheduled_orders": scheduled_orders,
            "blocked_orders": [],
            "forecast_orders": forecast_orders,
            "equipment_status": self.queue_service.simulation.equipment_status_summary(),
            "metrics": metrics,
        }
        return self.queue_service.last_schedule

    def _build_schedule_from_solution(
        self,
        orders: list[dict[str, Any]],
        task_records: list[dict[str, Any]],
        solver: cp_model.CpSolver,
        schedule_origin: datetime,
    ) -> tuple[list[dict[str, Any]], Counter[str]]:
        busy_minutes: Counter[str] = Counter()
        by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in sorted(task_records, key=lambda item: (solver.Value(item["start"]), item["order"]["id"], item["sequence_index"])):
            task = record["task"]
            selected = next(item for item in record["alternatives"] if solver.BooleanValue(item["present"]))
            resource = selected["resource"]
            duration = int(selected["duration"])
            start_minute = int(solver.Value(record["start"]))
            end_minute = int(solver.Value(record["end"]))
            start_time = schedule_origin + timedelta(minutes=start_minute)
            end_time = schedule_origin + timedelta(minutes=end_minute)
            employee_ids, staff_windows = self._selected_staff_windows(record, solver, schedule_origin)
            if task["step_kind"] == "detection":
                busy_minutes[resource["id"]] += duration
            step = {
                "step_kind": task["step_kind"],
                "project_id": task.get("id"),
                "project_type": task["project_type"],
                "equipment_type": task.get("equipment_type") if task["step_kind"] == "detection" else None,
                "equipment_id": resource["id"] if task["step_kind"] == "detection" else None,
                "lab_area": task["lab_area"],
                "assigned_employee_ids": employee_ids,
                "resource_ids": [] if task["step_kind"] == "detection" else [resource["id"]],
                "constraint_detail": {
                    "operator_requirements": self.queue_service._operator_requirements(task),
                    "equipment_performance_factor": float(resource.get("performance_factor", 1.0) or 1.0),
                    "continuous_operation": bool(task.get("continuous_operation")),
                    "can_cross_workday": bool(task.get("can_cross_workday")),
                    "staff_windows": staff_windows,
                    "solver": "cp_sat",
                },
                "setup_minutes": int(task.get("setup_minutes", 0) or 0),
                "staff_role": task.get("staff_role"),
                "consumable_type": task.get("consumable_type"),
                "consumable_units": int(task.get("consumable_units_per_batch", 0) or 0),
                "sequence": record["sequence_index"],
                "start_minute": start_minute,
                "start_time": start_time.isoformat(),
                "duration_minutes": duration,
                "end_minute": end_minute,
                "end_time": end_time.isoformat(),
                "batch_count": min(int(resource.get("capacity", 1)), int(record["order"]["sample_quantity"])) if task["step_kind"] == "detection" else None,
                "required_batches": ceil(int(record["order"]["sample_quantity"]) / max(1, int(resource.get("capacity", 1)))) if task["step_kind"] == "detection" else None,
                "staff_start_time": staff_windows[0]["start_time"] if staff_windows else start_time.isoformat(),
                "staff_end_time": staff_windows[-1]["end_time"] if staff_windows else end_time.isoformat(),
            }
            by_order[record["order"]["id"]].append(step)

        scheduled_orders = []
        for order in orders:
            steps = sorted(by_order[order["id"]], key=lambda item: item["sequence"])
            if not steps:
                continue
            finish_time = self.queue_service._parse_datetime(steps[-1]["end_time"])
            promised = self.queue_service._order_promised_finish_time(order)
            scheduled_orders.append(
                {
                    **self.queue_service._serialize_order(order),
                    "status": QueueStatus.SCHEDULED,
                    "steps": steps,
                    "arrival_time": self.queue_service._order_arrival_time(order).isoformat(),
                    "promised_finish_time": promised.isoformat() if promised else None,
                    "estimated_finish_minute": int((finish_time - schedule_origin).total_seconds() // 60),
                    "estimated_finish_time": finish_time.isoformat(),
                    "sla_status": self.queue_service._sla_status(finish_time, promised),
                    "delay_minutes": self.queue_service._delay_minutes(finish_time, promised),
                }
            )
        return sorted(scheduled_orders, key=lambda order: order["steps"][0]["start_time"]), busy_minutes

    def _expand_order_tasks(self, order: dict[str, Any]) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        previous_lab_area: str | None = None
        preprocessing = order.get("preprocessing_profile")
        if preprocessing:
            tasks.append(
                {
                    "step_kind": "preprocessing",
                    "id": None,
                    "project_type": "preprocessing",
                    "equipment_type": "prep_station",
                    "lab_area": preprocessing.get("lab_area", "intake"),
                    "duration_minutes": int(preprocessing["required_minutes"]),
                    "setup_minutes": 0,
                    "operator_requirements": {
                        "required_operator_count": int(preprocessing.get("required_operator_count", 1)),
                        "required_roles": preprocessing.get("required_roles", ["sample_operator"]),
                        "supervision_mode": "exclusive",
                        "staff_phase": "full",
                    },
                    "resource_bucket": "preprocessing_resources",
                    "resource_type": preprocessing.get("resource_type", "prep_station"),
                }
            )
            previous_lab_area = preprocessing.get("lab_area", "intake")

        for project in self.queue_service._detection_flow_for_order(order):
            lab_area = self.queue_service._project_lab_area(project)
            if previous_lab_area and previous_lab_area != lab_area:
                transfer = self.queue_service.simulation.transfer_rule(previous_lab_area, lab_area)
                if transfer:
                    tasks.append(
                        {
                            "step_kind": "transfer",
                            "id": None,
                            "project_type": "sample_transfer",
                            "equipment_type": transfer.get("resource_type", "transfer_cart"),
                            "lab_area": lab_area,
                            "duration_minutes": int(transfer.get("duration_minutes", 10)),
                            "setup_minutes": 0,
                            "operator_requirements": {
                                "required_operator_count": int(transfer.get("required_operator_count", 1)),
                                "required_roles": transfer.get("required_roles", ["transfer_operator"]),
                                "supervision_mode": "exclusive",
                                "staff_phase": "full",
                            },
                            "resource_bucket": "transfer_resources",
                            "resource_type": transfer.get("resource_type", "transfer_cart"),
                            "from_lab_area": previous_lab_area,
                            "to_lab_area": lab_area,
                        }
                    )
            tasks.append({**project, "step_kind": "detection", "lab_area": lab_area})
            previous_lab_area = lab_area
        return tasks

    def _resource_alternatives(self, order: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
        if task["step_kind"] == "detection":
            return [
                {
                    "resource_id": equipment["id"],
                    "resource": equipment,
                    "duration": self._duration_for(order, task, equipment),
                }
                for equipment in self.queue_service.simulation.equipment_instances_for(task["equipment_type"])
            ]
        resources = self.queue_service.simulation.resources_for(task["resource_bucket"], task["resource_type"])
        return [
            {
                "resource_id": resource["resource_id"],
                "resource": {"id": resource["resource_id"], **resource, "capacity": 1},
                "duration": int(task["duration_minutes"]),
            }
            for resource in resources
        ]

    def _add_staff_constraints(
        self,
        model: cp_model.CpModel,
        order: dict[str, Any],
        task: dict[str, Any],
        task_index: int,
        start: Any,
        end: Any,
        horizon: int,
        staff_intervals: dict[str, list[Any]],
    ) -> list[dict[str, Any]]:
        del order
        requirements = self.queue_service._operator_requirements(task)
        required_count = int(requirements["required_operator_count"])
        roles = requirements.get("required_roles", [])
        candidates = [
            employee
            for employee in self.queue_service.simulation.employee_instances()
            if self.queue_service._employee_matches(employee, task, roles)
        ]
        if len(candidates) < required_count:
            raise RuntimeError(f"no_staff_candidate:{task['project_type']}")

        assignment_records = []
        assigned_bools = []
        for employee in candidates:
            assigned = model.NewBoolVar(f"{task['project_type']}_{task_index}_{employee['employee_id']}_assigned")
            assigned_bools.append(assigned)
            windows = self._staff_window_vars(model, task, task_index, employee["employee_id"], start, end, horizon, assigned)
            for window in windows:
                staff_intervals[employee["employee_id"]].append(window["interval"])
            assignment_records.append({"employee": employee, "assigned": assigned, "windows": windows})

        model.Add(sum(assigned_bools) == required_count)
        for role in roles:
            role_bools = [item["assigned"] for item in assignment_records if role in item["employee"].get("roles", [])]
            if role_bools:
                model.Add(sum(role_bools) >= 1)
        return assignment_records

    def _staff_window_vars(
        self,
        model: cp_model.CpModel,
        task: dict[str, Any],
        task_index: int,
        employee_id: str,
        start: Any,
        end: Any,
        horizon: int,
        assigned: Any,
    ) -> list[dict[str, Any]]:
        requirements = self.queue_service._operator_requirements(task)
        phase = requirements.get("staff_phase", "running")
        setup_minutes = int(task.get("setup_minutes", 0) or 0)
        if setup_minutes <= 0 and phase in {"setup", "setup_unload"}:
            setup_minutes = min(30, max(1, int(task.get("duration_minutes", 30))))
        if phase in {"setup", "setup_only"}:
            return [self._fixed_size_staff_interval(model, task_index, employee_id, "setup", start, setup_minutes, horizon, assigned)]
        if phase == "setup_unload":
            setup = self._fixed_size_staff_interval(model, task_index, employee_id, "setup", start, setup_minutes, horizon, assigned)
            unload_start = model.NewIntVar(0, horizon, f"{task_index}_{employee_id}_unload_start")
            model.Add(unload_start == end - setup_minutes)
            unload = self._fixed_size_staff_interval(model, task_index, employee_id, "unload", unload_start, setup_minutes, horizon, assigned)
            return [setup, unload]
        size = model.NewIntVar(0, horizon, f"{task_index}_{employee_id}_staff_size")
        model.Add(size == end - start)
        interval = model.NewOptionalIntervalVar(start, size, end, assigned, f"{task_index}_{employee_id}_staff_full")
        return [{"phase": "full", "start": start, "end": end, "interval": interval}]

    def _fixed_size_staff_interval(
        self,
        model: cp_model.CpModel,
        task_index: int,
        employee_id: str,
        phase: str,
        start: Any,
        duration: int,
        horizon: int,
        assigned: Any,
    ) -> dict[str, Any]:
        window_end = model.NewIntVar(0, horizon, f"{task_index}_{employee_id}_{phase}_end")
        model.Add(window_end == start + duration)
        interval = model.NewOptionalIntervalVar(start, duration, window_end, assigned, f"{task_index}_{employee_id}_{phase}")
        return {"phase": phase, "start": start, "end": window_end, "interval": interval}

    def _add_consumable_constraint(
        self,
        model: cp_model.CpModel,
        order: dict[str, Any],
        task: dict[str, Any],
        task_index: int,
        start: Any,
        horizon: int,
        consumable_windows: dict[str, dict[str, Any]],
    ) -> None:
        units = int(task.get("consumable_units_per_batch", 0) or 0)
        consumable_type = task.get("consumable_type")
        capacity = self.queue_service.simulation.consumable_capacity(consumable_type)
        if not consumable_type or capacity is None or units <= 0:
            return
        required_batches = ceil(int(order["sample_quantity"]) / max(1, self.queue_service.simulation.equipment_capacity(task["equipment_type"])))
        demand = units * required_batches
        if demand > capacity:
            raise RuntimeError(f"consumable_capacity_exceeded:{consumable_type}")
        end = model.NewIntVar(0, horizon + 1440, f"{task_index}_{consumable_type}_window_end")
        model.Add(end == start + 1440)
        interval = model.NewIntervalVar(start, 1440, end, f"{task_index}_{consumable_type}_daily_window")
        window = consumable_windows.setdefault(
            consumable_type,
            {"intervals": [], "demands": [], "capacity": capacity},
        )
        window["intervals"].append(interval)
        window["demands"].append(demand)

    def _add_calendar_constraint(
        self,
        model: cp_model.CpModel,
        start: Any,
        duration: int,
        present: Any,
        task: dict[str, Any],
        schedule_origin: datetime,
        horizon: int,
    ) -> None:
        intervals = self._allowed_start_intervals(task, duration, schedule_origin, horizon)
        if not intervals:
            model.Add(start < 0).OnlyEnforceIf(present)
            return
        model.AddLinearExpressionInDomain(start, cp_model.Domain.FromIntervals(intervals)).OnlyEnforceIf(present)

    def _allowed_start_intervals(
        self,
        task: dict[str, Any],
        duration: int,
        schedule_origin: datetime,
        horizon: int,
    ) -> list[list[int]]:
        continuous = bool(task.get("continuous_operation") or task.get("can_cross_workday"))
        intervals: list[list[int]] = []
        latest_time = schedule_origin + timedelta(minutes=horizon)
        day = schedule_origin.date()
        while datetime.combine(day, datetime.min.time(), tzinfo=schedule_origin.tzinfo) <= latest_time + timedelta(days=1):
            if day.weekday() < 5:
                if continuous:
                    intervals.extend(
                        self._minute_interval(
                            datetime.combine(day, datetime.strptime("09:00", "%H:%M").time(), tzinfo=schedule_origin.tzinfo),
                            datetime.combine(day, datetime.strptime("17:59", "%H:%M").time(), tzinfo=schedule_origin.tzinfo),
                            schedule_origin,
                            horizon,
                        )
                    )
                elif task.get("project_type") == "environmental_check":
                    intervals.extend(
                        self._fitting_start_interval(
                            datetime.combine(day, datetime.strptime("09:00", "%H:%M").time(), tzinfo=schedule_origin.tzinfo),
                            datetime.combine(day, datetime.strptime("18:00", "%H:%M").time(), tzinfo=schedule_origin.tzinfo),
                            duration,
                            schedule_origin,
                            horizon,
                        )
                    )
                else:
                    intervals.extend(
                        self._fitting_start_interval(
                            datetime.combine(day, datetime.strptime("09:00", "%H:%M").time(), tzinfo=schedule_origin.tzinfo),
                            datetime.combine(day, datetime.strptime("12:00", "%H:%M").time(), tzinfo=schedule_origin.tzinfo),
                            duration,
                            schedule_origin,
                            horizon,
                        )
                    )
                    intervals.extend(
                        self._fitting_start_interval(
                            datetime.combine(day, datetime.strptime("13:00", "%H:%M").time(), tzinfo=schedule_origin.tzinfo),
                            datetime.combine(day, datetime.strptime("18:00", "%H:%M").time(), tzinfo=schedule_origin.tzinfo),
                            duration,
                            schedule_origin,
                            horizon,
                        )
                    )
            day += timedelta(days=1)
        return self._merge_intervals(intervals)

    def _fitting_start_interval(
        self,
        window_start: datetime,
        window_end: datetime,
        duration: int,
        schedule_origin: datetime,
        horizon: int,
    ) -> list[list[int]]:
        latest_start = window_end - timedelta(minutes=duration)
        if latest_start < window_start:
            return []
        return self._minute_interval(window_start, latest_start, schedule_origin, horizon)

    def _minute_interval(
        self,
        window_start: datetime,
        window_end: datetime,
        schedule_origin: datetime,
        horizon: int,
    ) -> list[list[int]]:
        lower = max(0, int(ceil((window_start - schedule_origin).total_seconds() / 60)))
        upper = min(horizon, int((window_end - schedule_origin).total_seconds() // 60))
        if upper < lower:
            return []
        return [[lower, upper]]

    def _merge_intervals(self, intervals: list[list[int]]) -> list[list[int]]:
        merged: list[list[int]] = []
        for lower, upper in sorted(intervals):
            if not merged or lower > merged[-1][1] + 1:
                merged.append([lower, upper])
            else:
                merged[-1][1] = max(merged[-1][1], upper)
        return merged

    def _selected_staff_windows(self, record: dict[str, Any], solver: cp_model.CpSolver, schedule_origin: datetime) -> tuple[list[str], list[dict[str, str]]]:
        employee_ids: list[str] = []
        windows: list[dict[str, str]] = []
        for assignment in record.get("staff_assignments", []):
            if not solver.BooleanValue(assignment["assigned"]):
                continue
            employee_id = assignment["employee"]["employee_id"]
            employee_ids.append(employee_id)
            for window in assignment["windows"]:
                start = schedule_origin + timedelta(minutes=int(solver.Value(window["start"])))
                end = schedule_origin + timedelta(minutes=int(solver.Value(window["end"])))
                windows.append(
                    {
                        "employee_id": employee_id,
                        "phase": window["phase"],
                        "start_time": start.isoformat(),
                        "end_time": end.isoformat(),
                    }
                )
        windows.sort(key=lambda item: (item["start_time"], item["employee_id"], item["phase"]))
        return sorted(employee_ids), windows

    def _add_locked_intervals(
        self,
        model: cp_model.CpModel,
        locked_steps: list[dict[str, Any]],
        schedule_origin: datetime,
        horizon: int,
        resource_intervals: dict[str, list[Any]],
        staff_intervals: dict[str, list[Any]],
    ) -> None:
        for index, step in enumerate(locked_steps):
            start_minute = int((self.queue_service._parse_datetime(step["start_time"]) - schedule_origin).total_seconds() // 60)
            end_minute = int((self.queue_service._parse_datetime(step["end_time"]) - schedule_origin).total_seconds() // 60)
            if end_minute <= 0 or start_minute >= horizon:
                continue
            start_minute = max(0, start_minute)
            end_minute = min(horizon, end_minute)
            duration = max(1, end_minute - start_minute)
            resource_ids = []
            if step.get("equipment_id"):
                resource_ids.append(step["equipment_id"])
            resource_ids.extend(step.get("resource_ids") or [])
            for resource_id in resource_ids:
                resource_intervals[resource_id].append(
                    model.NewIntervalVar(
                        start_minute,
                        duration,
                        end_minute,
                        f"locked_{index}_{resource_id}",
                    )
                )
            for employee_id in step.get("assigned_employee_ids") or []:
                staff_intervals[employee_id].append(
                    model.NewIntervalVar(
                        start_minute,
                        duration,
                        end_minute,
                        f"locked_{index}_{employee_id}",
                    )
                )

    def _duration_for(self, order: dict[str, Any], project: dict[str, Any], equipment: dict[str, Any]) -> int:
        capacity = max(1, int(equipment["capacity"]))
        required_batches = ceil(int(order["sample_quantity"]) / capacity)
        duration = int(project["duration_minutes"])
        if not project.get("duration_is_total"):
            duration *= required_batches
        if project.get("duration_is_total") and not project.get("continuous_operation"):
            duration += int(project.get("setup_minutes", 0) or 0)
        return self.queue_service._duration_for_equipment(duration, equipment)

    def _horizon_minutes(self, orders: list[dict[str, Any]], schedule_origin: datetime) -> int:
        latest_due = schedule_origin + timedelta(days=int(os.getenv("CP_SAT_ROLLING_HORIZON_DAYS", "7")) + 1)
        estimated = 0
        for order in orders:
            promised = self.queue_service._order_promised_finish_time(order)
            if promised and promised > latest_due:
                latest_due = promised
            estimated += self.queue_service._estimate_order_duration(order)
        horizon_from_due = int((latest_due - schedule_origin).total_seconds() // 60)
        return max(60, horizon_from_due + estimated + 24 * 60)

    def _fallback(
        self,
        orders: list[dict[str, Any]],
        reason: str,
        started_at: float,
        forecast_orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        schedule = self.queue_service.rebuild_schedule(orders, strategy=self.DEFAULT_FALLBACK_STRATEGY)
        combined_forecast = [*schedule.get("forecast_orders", []), *(forecast_orders or [])]
        schedule["forecast_orders"] = combined_forecast
        schedule["metrics"] = {
            **schedule.get("metrics", {}),
            "selected_strategy": "cp_sat_rolling",
            "solver_used": "cp_sat",
            "solver_status": "fallback",
            "solver_latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "fallback_used": True,
            "fallback_reason": reason,
            "forecast_count": len(combined_forecast),
        }
        return schedule

    def _status_name(self, status: int) -> str:
        if status == cp_model.OPTIMAL:
            return "optimal"
        if status == cp_model.FEASIBLE:
            return "feasible"
        if status == cp_model.INFEASIBLE:
            return "infeasible"
        if status == cp_model.MODEL_INVALID:
            return "model_invalid"
        return "unknown"
