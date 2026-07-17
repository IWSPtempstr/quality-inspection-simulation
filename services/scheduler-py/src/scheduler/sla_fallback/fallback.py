"""Greedy SLA fallback over an immutable snapshot, with no solver dependency."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from scheduler.contracts.candidate import FallbackReason, ScheduleCandidate
from scheduler.contracts.snapshot import SchedulingSnapshot

_HORIZON_MINUTES = 7 * 24 * 60
_PRIORITY = {"vip": 0, "urgent": 1, "normal": 2}
class FallbackRejectedError(ValueError):
    """Raised when a CP-SAT result does not authorize deterministic fallback."""


@dataclass(frozen=True)
class _Step:
    id: str
    order_id: str
    index: int
    duration: int
    preprocessing_minutes: int
    transfer_minutes: int
    preprocessing_resource_id: str | None
    transfer_resource_id: str | None
    equipment_ids: tuple[str, ...]
    employee_ids: tuple[str, ...]
    required_skill: str | None
    required_role: str | None
    consumables: dict[str, int]
    frozen: dict[str, Any] | None
    order_sort_key: tuple[Any, ...]


@dataclass(frozen=True)
class _Assignment:
    step: _Step
    start: int
    end: int
    equipment_id: str
    employee_id: str


def build_fallback_candidate(
    snapshot: SchedulingSnapshot,
    *,
    trigger: FallbackReason,
    cp_sat_status: str,
    input_size_limit: int | None = None,
) -> ScheduleCandidate:
    """Build a repeatable candidate only after an explicit, non-feasible CP-SAT failure.

    ``trigger`` is deliberately supplied by the caller's measured solver outcome.
    It is validated here so a feasible or optimal CP-SAT result can never be
    overwritten by the fallback. The function has no transport, persistence, or
    scheduling-engine side effects.
    """
    _validate_trigger(snapshot, trigger, cp_sat_status, input_size_limit)
    equipment = _records_by_id(snapshot.resources.get("equipment"))
    employees = _records_by_id(snapshot.resources.get("employees"))
    preprocessing = _stage_resources(snapshot.resources, "preprocessing")
    transfer = _stage_resources(snapshot.resources, "transfer")
    frozen = {str(item.get("id")): item for item in snapshot.frozen_steps}
    steps = _steps(snapshot, equipment, employees, frozen)
    reservations = _Reservations(snapshot.as_of, equipment, employees, preprocessing, transfer)
    assignments: list[_Assignment] = []
    blocked: list[dict[str, str]] = []
    remaining = _consumables(snapshot.resources.get("consumables"))
    order_end: dict[str, int] = {}
    valid_frozen: dict[str, _Assignment] = {}

    # Frozen work is immutable capacity already consumed before any greedy choice.
    for step in steps:
        if step.frozen is None:
            continue
        frozen_assignment = _frozen_assignment(step, equipment, employees)
        if frozen_assignment is None:
            blocked.append({"step_id": step.id, "reason": "invalid_frozen_step"})
            continue
        reservations.reserve(frozen_assignment)
        valid_frozen[step.id] = frozen_assignment
        assignments.append(frozen_assignment)

    for step in steps:
        if step.frozen is not None:
            frozen_assignment = valid_frozen.get(step.id)
            if frozen_assignment is not None:
                order_end[step.order_id] = frozen_assignment.end
            continue

        reason = _preflight_reason(step, equipment, employees, preprocessing, transfer, remaining)
        if reason is not None:
            blocked.append({"step_id": step.id, "reason": reason})
            continue
        assignment = _earliest_assignment(
            step,
            order_end.get(step.order_id, 0),
            _next_frozen_start(steps, step),
            equipment,
            employees,
            reservations,
        )
        if assignment is None:
            blocked.append({"step_id": step.id, "reason": "no_feasible_resource_window"})
            continue
        reservations.reserve(assignment)
        assignments.append(assignment)
        order_end[step.order_id] = assignment.end
        for name, quantity in step.consumables.items():
            remaining[name] -= quantity

    rendered = [_render_assignment(item, snapshot.as_of) for item in assignments]
    rendered.sort(key=lambda item: (str(item["start"]), str(item["step_id"])))
    return ScheduleCandidate.model_validate(
        {
            "input_hash": snapshot.input_hash,
            "algorithm_used": "sla_fallback",
            "solver_status": "fallback_completed",
            "fallback_used": True,
            "fallback_reason": trigger,
            "blocked_steps": blocked,
            "schedule": {"steps": rendered},
            "metrics": {
                "scheduled_step_count": len(rendered),
                "blocked_step_count": len(blocked),
                "blocked_step_ids": sorted(item["step_id"] for item in blocked),
            },
        }
    )


def _validate_trigger(
    snapshot: SchedulingSnapshot,
    trigger: FallbackReason,
    cp_sat_status: str,
    input_size_limit: int | None,
) -> None:
    status = cp_sat_status.strip().lower()
    if status in {"feasible", "optimal"}:
        raise FallbackRejectedError("CP-SAT feasible or optimal results cannot use fallback")
    if trigger == "cp_sat_infeasible" and status != "infeasible":
        raise FallbackRejectedError("infeasible trigger requires an INFEASIBLE CP-SAT result")
    if trigger == "cp_sat_timeout_without_feasible_solution" and status not in {
        "unknown",
        "timeout_without_feasible_solution",
    }:
        raise FallbackRejectedError("timeout trigger requires no feasible CP-SAT solution")
    if trigger == "cp_sat_execution_error" and status not in {
        "execution_error",
        "initialization_error",
        "error",
    }:
        raise FallbackRejectedError("execution trigger requires a CP-SAT execution or init error")
    if trigger == "input_size_protection_threshold_exceeded":
        if input_size_limit is None or input_size_limit < 1:
            raise FallbackRejectedError("input-size trigger requires a positive protection limit")
        if _work_count(snapshot) <= input_size_limit:
            raise FallbackRejectedError("input-size protection threshold was not exceeded")


def _work_count(snapshot: SchedulingSnapshot) -> int:
    return sum(len(_records(order.get("steps"))) for order in snapshot.orders)


def _steps(
    snapshot: SchedulingSnapshot,
    equipment: dict[str, dict[str, Any]],
    employees: dict[str, dict[str, Any]],
    frozen: dict[str, dict[str, Any]],
) -> list[_Step]:
    result: list[_Step] = []
    for order in snapshot.orders:
        order_id = str(order["id"])
        promise = _minute(order.get("promise_at"), snapshot.as_of, _HORIZON_MINUTES)
        arrival = _minute(order.get("arrival_at"), snapshot.as_of, _HORIZON_MINUTES)
        priority = _PRIORITY.get(str(order.get("priority", "normal")).lower(), _PRIORITY["normal"])
        order_key = (promise > 0, promise, priority, promise, arrival, order_id)
        for index, raw in enumerate(_records(order.get("steps"))):
            step_id = str(raw["id"])
            prep = max(0, int(raw.get("preprocessing_minutes", 0)))
            transfer = max(0, int(raw.get("transfer_minutes", 0)))
            result.append(
                _Step(
                    id=step_id,
                    order_id=order_id,
                    index=index,
                    duration=max(1, int(raw.get("duration_minutes", 1)) + prep + transfer),
                    preprocessing_minutes=prep,
                    transfer_minutes=transfer,
                    preprocessing_resource_id=_optional_string(
                        raw.get("preprocessing_resource_id")
                    ),
                    transfer_resource_id=_optional_string(raw.get("transfer_resource_id")),
                    equipment_ids=tuple(
                        sorted(
                            str(item)
                            for item in raw.get("equipment_ids", equipment)
                            if str(item) in equipment
                        )
                    ),
                    employee_ids=tuple(
                        sorted(
                            str(item)
                            for item in raw.get("employee_ids", employees)
                            if str(item) in employees
                        )
                    ),
                    required_skill=_optional_string(raw.get("required_skill")),
                    required_role=_optional_string(raw.get("required_role")),
                    consumables=_consumables(raw.get("consumables")),
                    frozen=frozen.get(step_id),
                    order_sort_key=order_key,
                )
            )
    return sorted(result, key=lambda item: (*item.order_sort_key, item.index, item.id))


def _preflight_reason(
    step: _Step,
    equipment: dict[str, dict[str, Any]],
    employees: dict[str, dict[str, Any]],
    preprocessing: dict[str, dict[str, Any]],
    transfer: dict[str, dict[str, Any]],
    remaining: dict[str, int],
) -> str | None:
    if not step.equipment_ids:
        return "no_eligible_equipment"
    if not any(
        _employee_matches(employees[employee_id], step) for employee_id in step.employee_ids
    ):
        return "no_eligible_employee"
    if step.preprocessing_minutes and step.preprocessing_resource_id not in preprocessing:
        return "no_eligible_preprocessing_resource"
    if step.transfer_minutes and step.transfer_resource_id not in transfer:
        return "no_eligible_transfer_resource"
    if any(remaining.get(name, 0) < quantity for name, quantity in step.consumables.items()):
        return "insufficient_consumables"
    return None


def _earliest_assignment(
    step: _Step,
    release: int,
    next_frozen_start: int | None,
    equipment: dict[str, dict[str, Any]],
    employees: dict[str, dict[str, Any]],
    reservations: _Reservations,
) -> _Assignment | None:
    employee_ids = [item for item in step.employee_ids if _employee_matches(employees[item], step)]
    for start in range(max(0, release), _HORIZON_MINUTES - step.duration + 1):
        end = start + step.duration
        if next_frozen_start is not None and end > next_frozen_start:
            break
        for equipment_id in step.equipment_ids:
            if not reservations.equipment_available(equipment_id, start, end):
                continue
            for employee_id in employee_ids:
                if not reservations.employee_available(employee_id, start, end):
                    continue
                if not reservations.stage_available(step, start, end):
                    continue
                return _Assignment(step, start, end, equipment_id, employee_id)
    return None


def _next_frozen_start(steps: list[_Step], step: _Step) -> int | None:
    """Return the next fixed point in this order, preserving ordered steps."""
    starts = [
        int(item.frozen["start"])
        for item in steps
        if item.order_id == step.order_id
        and item.index > step.index
        and item.frozen is not None
        and isinstance(item.frozen.get("start"), int)
    ]
    return min(starts) if starts else None


class _Reservations:
    def __init__(
        self,
        as_of: datetime,
        equipment: dict[str, dict[str, Any]],
        employees: dict[str, dict[str, Any]],
        preprocessing: dict[str, dict[str, Any]],
        transfer: dict[str, dict[str, Any]],
    ) -> None:
        self.as_of = as_of
        self.equipment = equipment
        self.employees = employees
        self.preprocessing = preprocessing
        self.transfer = transfer
        self.equipment_windows: dict[str, list[tuple[int, int]]] = {}
        self.employee_windows: dict[str, list[tuple[int, int]]] = {}
        self.preprocessing_windows: dict[str, list[tuple[int, int]]] = {}
        self.transfer_windows: dict[str, list[tuple[int, int]]] = {}

    def reserve(self, assignment: _Assignment) -> None:
        self.equipment_windows.setdefault(assignment.equipment_id, []).append(
            (assignment.start, assignment.end)
        )
        self.employee_windows.setdefault(assignment.employee_id, []).append(
            (assignment.start, assignment.end)
        )
        step = assignment.step
        if step.preprocessing_minutes and step.preprocessing_resource_id is not None:
            self.preprocessing_windows.setdefault(step.preprocessing_resource_id, []).append(
                (assignment.start, assignment.start + step.preprocessing_minutes)
            )
        if step.transfer_minutes and step.transfer_resource_id is not None:
            self.transfer_windows.setdefault(step.transfer_resource_id, []).append(
                (assignment.end - step.transfer_minutes, assignment.end)
            )

    def equipment_available(self, resource_id: str, start: int, end: int) -> bool:
        resource = self.equipment[resource_id]
        return self._available(
            resource,
            self.equipment_windows.get(resource_id, []),
            start,
            end,
            capacity=max(1, int(resource.get("capacity", 1))),
            blackout_fields=("maintenance", "failures"),
        )

    def employee_available(self, resource_id: str, start: int, end: int) -> bool:
        resource = self.employees[resource_id]
        if not _within_shift(resource, start, end, self.as_of):
            return False
        return self._available(
            resource,
            self.employee_windows.get(resource_id, []),
            start,
            end,
            capacity=1,
            blackout_fields=("unavailability",),
        )

    def stage_available(self, step: _Step, start: int, end: int) -> bool:
        if step.preprocessing_minutes and step.preprocessing_resource_id is not None:
            resource_id = step.preprocessing_resource_id
            if not self._available(
                self.preprocessing[resource_id],
                self.preprocessing_windows.get(resource_id, []),
                start,
                start + step.preprocessing_minutes,
                capacity=max(1, int(self.preprocessing[resource_id].get("capacity", 1))),
                blackout_fields=("maintenance", "failures"),
            ):
                return False
        if step.transfer_minutes and step.transfer_resource_id is not None:
            resource_id = step.transfer_resource_id
            if not self._available(
                self.transfer[resource_id],
                self.transfer_windows.get(resource_id, []),
                end - step.transfer_minutes,
                end,
                capacity=max(1, int(self.transfer[resource_id].get("capacity", 1))),
                blackout_fields=("maintenance", "failures"),
            ):
                return False
        return True

    def _available(
        self,
        resource: dict[str, Any],
        windows: list[tuple[int, int]],
        start: int,
        end: int,
        *,
        capacity: int,
        blackout_fields: tuple[str, ...],
    ) -> bool:
        if any(
            _overlaps(start, end, item_start, item_end)
            for item_start, item_end in _blackouts(resource, self.as_of, blackout_fields)
        ):
            return False
        points = {start, end}
        for item_start, item_end in windows:
            if _overlaps(start, end, item_start, item_end):
                points.update((max(start, item_start), min(end, item_end)))
        return all(
            sum(
                _overlaps(point, point + 1, item_start, item_end)
                for item_start, item_end in windows
            )
            < capacity
            for point in points
            if point < end
        )


def _frozen_assignment(
    step: _Step,
    equipment: dict[str, dict[str, Any]],
    employees: dict[str, dict[str, Any]],
) -> _Assignment | None:
    frozen = step.frozen
    if frozen is None:
        return None
    try:
        start, end = int(frozen["start"]), int(frozen["end"])
        equipment_id, employee_id = str(frozen["equipment_id"]), str(frozen["employee_id"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        start < 0
        or end <= start
        or equipment_id not in equipment
        or employee_id not in employees
        or equipment_id not in step.equipment_ids
        or employee_id not in step.employee_ids
    ):
        return None
    return _Assignment(step, start, end, equipment_id, employee_id)


def _records_by_id(value: Any) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in _records(value) if "id" in item}


def _stage_resources(resources: dict[str, Any], stage: str) -> dict[str, dict[str, Any]]:
    result = _records_by_id(resources.get("equipment"))
    result.update(_records_by_id(resources.get(f"{stage}_resources")))
    return result


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _consumables(value: Any) -> dict[str, int]:
    return {str(key): int(item) for key, item in value.items()} if isinstance(value, dict) else {}


def _employee_matches(employee: dict[str, Any], step: _Step) -> bool:
    skills = {str(item) for item in employee.get("skills", [])}
    roles = {str(item) for item in employee.get("roles", [])}
    return (step.required_skill is None or step.required_skill in skills) and (
        step.required_role is None or step.required_role in roles
    )


def _within_shift(resource: dict[str, Any], start: int, end: int, as_of: datetime) -> bool:
    shifts = _records(resource.get("shifts"))
    if not shifts:
        return True
    return any(
        shift_start is not None
        and shift_end is not None
        and start >= shift_start
        and end <= shift_end
        for shift in shifts
        for shift_start, shift_end in [
            (_optional_minute(shift.get("start"), as_of), _optional_minute(shift.get("end"), as_of))
        ]
    )


def _blackouts(
    resource: dict[str, Any], as_of: datetime, fields: tuple[str, ...]
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for field in fields:
        for blackout in _records(resource.get(field)):
            start, end = (
                _optional_minute(blackout.get("start"), as_of),
                _optional_minute(blackout.get("end"), as_of),
            )
            if start is not None and end is not None and end > start:
                result.append((start, end))
    return result


def _minute(value: Any, as_of: datetime, default: int) -> int:
    parsed = _optional_minute(value, as_of)
    return parsed if parsed is not None else default


def _optional_minute(value: Any, as_of: datetime) -> int | None:
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return None
    return int((parsed.astimezone(UTC) - as_of).total_seconds() // 60)


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _overlaps(start: int, end: int, other_start: int, other_end: int) -> bool:
    return start < other_end and other_start < end


def _render_assignment(assignment: _Assignment, as_of: datetime) -> dict[str, Any]:
    return {
        "step_id": assignment.step.id,
        "order_id": assignment.step.order_id,
        "start": _timestamp(as_of, assignment.start),
        "end": _timestamp(as_of, assignment.end),
        "equipment_id": assignment.equipment_id,
        "employee_id": assignment.employee_id,
        "frozen": assignment.step.frozen is not None,
    }


def _timestamp(as_of: datetime, minute: int) -> str:
    return (as_of + timedelta(minutes=minute)).astimezone(UTC).isoformat().replace("+00:00", "Z")
