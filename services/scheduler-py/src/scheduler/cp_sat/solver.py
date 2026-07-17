"""Pure CP-SAT scheduling over the opaque, immutable S1 snapshot."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ortools.sat.python import cp_model

from scheduler.contracts.candidate import ScheduleCandidate
from scheduler.contracts.snapshot import SchedulingSnapshot

_WEIGHTS = {"vip": 100, "urgent": 10, "normal": 1}
_HORIZON_MINUTES = 7 * 24 * 60


@dataclass(frozen=True)
class _Step:
    id: str
    order_id: str
    duration: int
    preprocessing_minutes: int
    transfer_minutes: int
    preprocessing_resource_id: str | None
    transfer_resource_id: str | None
    equipment_ids: tuple[str, ...]
    employee_ids: tuple[str, ...]
    due: int
    weight: int
    formal_start: int | None
    required_skill: str | None
    required_role: str | None
    consumables: dict[str, int]
    frozen: dict[str, Any] | None


@dataclass
class _Vars:
    step: _Step
    start: Any
    end: Any
    equipment: dict[str, Any]
    employee: dict[str, Any]


def solve_snapshot(
    snapshot: SchedulingSnapshot, *, time_limit_seconds: int = 10
) -> ScheduleCandidate:
    """Return a CP-SAT candidate without persistence, transport, or side effects.

    Controlled S2 fixtures use order ``steps`` with ``duration_minutes``,
    ``equipment_ids`` and ``employee_ids``. Resources provide equipment and
    employees by id. Blackouts use UTC ``start``/``end`` ranges under
    equipment ``maintenance``/``failures`` and employee ``unavailability``.
    Frozen entries provide minute offsets plus equipment/employee ids.
    """
    equipment = _record_map(snapshot.resources.get("equipment"))
    employees = _record_map(snapshot.resources.get("employees"))
    preprocessing_resources = _stage_resource_map(snapshot.resources, "preprocessing")
    transfer_resources = _stage_resource_map(snapshot.resources, "transfer")
    frozen = {str(item.get("id")): item for item in snapshot.frozen_steps}
    steps = _parse_steps(snapshot, equipment, employees, frozen)
    blocked = _preflight(
        steps,
        equipment,
        employees,
        snapshot.resources,
        preprocessing_resources,
        transfer_resources,
    )
    blocked_ids = {item["step_id"] for item in blocked}
    scheduled_steps = [step for step in steps if step.id not in blocked_ids]
    model = cp_model.CpModel()
    variables = _variables(model, scheduled_steps, employees)
    _resource_constraints(
        model,
        variables,
        equipment,
        employees,
        preprocessing_resources,
        transfer_resources,
        snapshot.as_of,
    )
    _precedence_constraints(model, variables)
    status, solver = _solve(model, variables, time_limit_seconds)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        blocked.extend(
            {"step_id": step.id, "reason": "cp_sat_infeasible"} for step in scheduled_steps
        )
        return _candidate(snapshot, "infeasible", [], blocked)
    return _candidate(
        snapshot,
        "optimal" if status == cp_model.OPTIMAL else "feasible",
        _result_steps(solver, variables, snapshot.as_of),
        blocked,
    )


def _record_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {str(item["id"]): item for item in value if isinstance(item, dict) and "id" in item}


def _stage_resource_map(resources: dict[str, Any], stage: str) -> dict[str, dict[str, Any]]:
    """Resolve explicit stage resources, allowing existing equipment as a source."""
    result = _record_map(resources.get("equipment"))
    result.update(_record_map(resources.get(f"{stage}_resources")))
    return result


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _parse_steps(
    snapshot: SchedulingSnapshot,
    equipment: dict[str, dict[str, Any]],
    employees: dict[str, dict[str, Any]],
    frozen: dict[str, dict[str, Any]],
) -> list[_Step]:
    result: list[_Step] = []
    for order in snapshot.orders:
        order_id = str(order["id"])
        priority = str(order.get("priority", "normal")).lower()
        due = _as_minute(order.get("promise_at"), snapshot.as_of, _HORIZON_MINUTES)
        for raw in _records(order.get("steps")):
            step_id = str(raw["id"])
            preprocessing_minutes = max(0, int(raw.get("preprocessing_minutes", 0)))
            transfer_minutes = max(0, int(raw.get("transfer_minutes", 0)))
            result.append(
                _Step(
                    id=step_id,
                    order_id=order_id,
                    duration=max(
                        1,
                        int(raw.get("duration_minutes", 1))
                        + preprocessing_minutes
                        + transfer_minutes,
                    ),
                    preprocessing_minutes=preprocessing_minutes,
                    transfer_minutes=transfer_minutes,
                    preprocessing_resource_id=_as_optional_string(
                        raw.get("preprocessing_resource_id")
                    ),
                    transfer_resource_id=_as_optional_string(raw.get("transfer_resource_id")),
                    equipment_ids=tuple(
                        item
                        for item in raw.get("equipment_ids", equipment.keys())
                        if item in equipment
                    ),
                    employee_ids=tuple(
                        item
                        for item in raw.get("employee_ids", employees.keys())
                        if item in employees
                    ),
                    due=due,
                    weight=_WEIGHTS.get(priority, 1),
                    formal_start=_as_optional_minute(raw.get("formal_start"), snapshot.as_of),
                    required_skill=_as_optional_string(raw.get("required_skill")),
                    required_role=_as_optional_string(raw.get("required_role")),
                    consumables=_consumable_requirements(raw.get("consumables")),
                    frozen=frozen.get(step_id),
                )
            )
    return result


def _preflight(
    steps: Iterable[_Step],
    equipment: dict[str, dict[str, Any]],
    employees: dict[str, dict[str, Any]],
    resources: dict[str, Any],
    preprocessing_resources: dict[str, dict[str, Any]],
    transfer_resources: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    blocked: list[dict[str, str]] = []
    remaining = _remaining_consumables(resources.get("consumables"))
    for step in steps:
        if not step.equipment_ids:
            blocked.append({"step_id": step.id, "reason": "no_eligible_equipment"})
        elif not _eligible_employee_ids(step, employees):
            blocked.append({"step_id": step.id, "reason": "no_eligible_employee"})
        elif not _has_stage_resource(
            step.preprocessing_minutes, step.preprocessing_resource_id, preprocessing_resources
        ):
            blocked.append({"step_id": step.id, "reason": "no_eligible_preprocessing_resource"})
        elif not _has_stage_resource(
            step.transfer_minutes, step.transfer_resource_id, transfer_resources
        ):
            blocked.append({"step_id": step.id, "reason": "no_eligible_transfer_resource"})
        elif not _has_consumables(step, remaining):
            blocked.append({"step_id": step.id, "reason": "insufficient_consumables"})
        elif step.frozen is not None and not _valid_frozen(step, equipment, employees):
            blocked.append({"step_id": step.id, "reason": "invalid_frozen_step"})
        else:
            for key, amount in step.consumables.items():
                remaining[key] -= amount
    return blocked


def _has_stage_resource(
    minutes: int, resource_id: str | None, resources: dict[str, dict[str, Any]]
) -> bool:
    return minutes == 0 or (resource_id is not None and resource_id in resources)


def _consumable_requirements(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): int(amount) for key, amount in value.items()}


def _remaining_consumables(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): int(amount) for key, amount in value.items()}


def _has_consumables(step: _Step, available: dict[str, int]) -> bool:
    if not step.consumables:
        return True
    return all(int(available.get(key, 0)) >= amount for key, amount in step.consumables.items())


def _eligible_employee_ids(step: _Step, employees: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        employee_id
        for employee_id in step.employee_ids
        if _employee_matches(employees[employee_id], step)
    )


def _employee_matches(employee: dict[str, Any], step: _Step) -> bool:
    skills = {str(value) for value in employee.get("skills", [])}
    roles = {str(value) for value in employee.get("roles", [])}
    return (step.required_skill is None or step.required_skill in skills) and (
        step.required_role is None or step.required_role in roles
    )


def _valid_frozen(
    step: _Step, equipment: dict[str, dict[str, Any]], employees: dict[str, dict[str, Any]]
) -> bool:
    frozen = step.frozen
    if frozen is None:
        return True
    keys = {"start", "end", "equipment_id", "employee_id"}
    return (
        keys <= frozen.keys()
        and str(frozen["equipment_id"]) in equipment
        and str(frozen["employee_id"]) in employees
        and str(frozen["equipment_id"]) in step.equipment_ids
        and str(frozen["employee_id"]) in step.employee_ids
    )


def _variables(
    model: Any,
    steps: list[_Step],
    employee_records: dict[str, dict[str, Any]],
) -> list[_Vars]:
    result: list[_Vars] = []
    for step in steps:
        start = model.NewIntVar(0, _HORIZON_MINUTES, f"{step.id}_start")
        end = model.NewIntVar(0, _HORIZON_MINUTES + step.duration, f"{step.id}_end")
        model.Add(end == start + step.duration)
        equipment = {
            resource_id: model.NewBoolVar(f"{step.id}_equipment_{resource_id}")
            for resource_id in step.equipment_ids
        }
        employee = {
            resource_id: model.NewBoolVar(f"{step.id}_employee_{resource_id}")
            for resource_id in step.employee_ids
        }
        model.AddExactlyOne(equipment.values())
        model.AddExactlyOne(employee.values())
        for resource_id, selected in employee.items():
            if not _employee_matches(employee_records[resource_id], step):
                model.Add(selected == 0)
        if step.frozen is not None:
            model.Add(start == int(step.frozen["start"]))
            model.Add(end == int(step.frozen["end"]))
            _choose_frozen(model, equipment, str(step.frozen["equipment_id"]))
            _choose_frozen(model, employee, str(step.frozen["employee_id"]))
        result.append(_Vars(step, start, end, equipment, employee))
    return result


def _choose_frozen(model: Any, choices: dict[str, Any], selected: str) -> None:
    for resource_id, value in choices.items():
        model.Add(value == (resource_id == selected))


def _resource_constraints(
    model: Any,
    variables: list[_Vars],
    equipment: dict[str, dict[str, Any]],
    employees: dict[str, dict[str, Any]],
    preprocessing_resources: dict[str, dict[str, Any]],
    transfer_resources: dict[str, dict[str, Any]],
    as_of: datetime,
) -> None:
    for resource_id, resource in equipment.items():
        intervals = _resource_intervals(model, variables, resource_id, "equipment")
        intervals += _blackouts(model, resource, as_of, ("maintenance", "failures"))
        capacity = max(1, int(resource.get("capacity", 1)))
        model.AddCumulative(intervals, [1] * len(intervals), capacity)
    for resource_id, resource in employees.items():
        intervals = _resource_intervals(model, variables, resource_id, "employee")
        intervals += _blackouts(model, resource, as_of, ("unavailability",))
        model.AddNoOverlap(intervals)
        _constrain_shifts(model, variables, resource_id, resource, as_of)
    _stage_resource_constraints(model, variables, preprocessing_resources, "preprocessing", as_of)
    _stage_resource_constraints(model, variables, transfer_resources, "transfer", as_of)


def _stage_resource_constraints(
    model: Any,
    variables: list[_Vars],
    resources: dict[str, dict[str, Any]],
    stage: str,
    as_of: datetime,
) -> None:
    for resource_id, resource in resources.items():
        intervals = _stage_intervals(model, variables, resource_id, stage)
        intervals += _blackouts(model, resource, as_of, ("maintenance", "failures"))
        capacity = max(1, int(resource.get("capacity", 1)))
        model.AddCumulative(intervals, [1] * len(intervals), capacity)


def _constrain_shifts(
    model: Any,
    variables: list[_Vars],
    employee_id: str,
    employee: dict[str, Any],
    as_of: datetime,
) -> None:
    shifts = _records(employee.get("shifts"))
    if not shifts:
        return
    for item in variables:
        selected = item.employee.get(employee_id)
        if selected is None:
            continue
        fits: list[Any] = []
        for index, shift in enumerate(shifts):
            start = _as_optional_minute(shift.get("start"), as_of)
            end = _as_optional_minute(shift.get("end"), as_of)
            if start is None or end is None:
                continue
            fits_shift = model.NewBoolVar(f"{item.step.id}_{employee_id}_shift_{index}")
            model.Add(item.start >= start).OnlyEnforceIf(fits_shift)
            model.Add(item.end <= end).OnlyEnforceIf(fits_shift)
            fits.append(fits_shift)
        if fits:
            model.AddBoolOr([*fits, selected.Not()])
        else:
            model.Add(selected == 0)


def _resource_intervals(
    model: Any, variables: list[_Vars], resource_id: str, kind: str
) -> list[Any]:
    intervals: list[Any] = []
    for item in variables:
        choices = item.equipment if kind == "equipment" else item.employee
        if resource_id in choices:
            intervals.append(
                model.NewOptionalIntervalVar(
                    item.start,
                    item.step.duration,
                    item.end,
                    choices[resource_id],
                    f"{item.step.id}_{kind}_{resource_id}",
                )
            )
    return intervals


def _stage_intervals(model: Any, variables: list[_Vars], resource_id: str, stage: str) -> list[Any]:
    intervals: list[Any] = []
    for item in variables:
        if stage == "preprocessing":
            minutes = item.step.preprocessing_minutes
            selected = item.step.preprocessing_resource_id == resource_id
            start = item.start
        else:
            minutes = item.step.transfer_minutes
            selected = item.step.transfer_resource_id == resource_id
            start = item.end - minutes
        if minutes > 0 and selected:
            intervals.append(
                model.NewIntervalVar(
                    start,
                    minutes,
                    start + minutes,
                    f"{item.step.id}_{stage}_{resource_id}",
                )
            )
    return intervals


def _blackouts(
    model: Any,
    resource: dict[str, Any],
    as_of: datetime,
    fields: tuple[str, ...],
) -> list[Any]:
    result: list[Any] = []
    for field in fields:
        for blackout in _records(resource.get(field)):
            start = _as_optional_minute(blackout.get("start"), as_of)
            end = _as_optional_minute(blackout.get("end"), as_of)
            if start is None or end is None or end <= 0 or start >= _HORIZON_MINUTES:
                continue
            start, end = max(0, start), min(_HORIZON_MINUTES, end)
            result.append(model.NewIntervalVar(start, end - start, end, f"{field}_{len(result)}"))
    return result


def _precedence_constraints(model: Any, variables: list[_Vars]) -> None:
    grouped: dict[str, list[_Vars]] = {}
    for item in variables:
        grouped.setdefault(item.step.order_id, []).append(item)
    for ordered in grouped.values():
        for previous, following in zip(ordered, ordered[1:]):
            model.Add(previous.end <= following.start)


def _solve(model: Any, variables: list[_Vars], time_limit_seconds: int) -> tuple[Any, Any]:
    objectives = _objectives(model, variables)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 1
    status = cp_model.UNKNOWN
    for objective in objectives:
        model.Minimize(objective)
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return status, solver
        model.Add(objective == solver.Value(objective))
    return status, solver


def _objectives(model: Any, variables: list[_Vars]) -> list[Any]:
    weighted: list[Any] = []
    count: list[Any] = []
    minutes: list[Any] = []
    changes: list[Any] = []
    ends: list[Any] = []
    for item in variables:
        lateness = model.NewIntVar(0, _HORIZON_MINUTES * 2, f"{item.step.id}_lateness")
        model.AddMaxEquality(lateness, [item.end - item.step.due, 0])
        weighted.append(lateness * item.step.weight)
        minutes.append(lateness)
        ends.append(item.end)
        late = model.NewBoolVar(f"{item.step.id}_late")
        model.Add(lateness > 0).OnlyEnforceIf(late)
        model.Add(lateness == 0).OnlyEnforceIf(late.Not())
        count.append(late)
        if item.step.frozen is None and item.step.formal_start is not None:
            changed = model.NewBoolVar(f"{item.step.id}_changed")
            model.Add(item.start != item.step.formal_start).OnlyEnforceIf(changed)
            model.Add(item.start == item.step.formal_start).OnlyEnforceIf(changed.Not())
            changes.append(changed)
    makespan = model.NewIntVar(0, _HORIZON_MINUTES * 2, "makespan")
    model.AddMaxEquality(makespan, ends or [0])
    return [sum(weighted), sum(count), sum(minutes), sum(changes), makespan]


def _result_steps(solver: Any, variables: list[_Vars], as_of: datetime) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in variables:
        equipment_id = next(key for key, value in item.equipment.items() if solver.Value(value))
        employee_id = next(key for key, value in item.employee.items() if solver.Value(value))
        result.append(
            {
                "step_id": item.step.id,
                "order_id": item.step.order_id,
                "start": _timestamp(as_of, solver.Value(item.start)),
                "end": _timestamp(as_of, solver.Value(item.end)),
                "equipment_id": equipment_id,
                "employee_id": employee_id,
                "frozen": item.step.frozen is not None,
            }
        )
    return sorted(result, key=lambda item: (item["start"], item["step_id"]))


def _candidate(
    snapshot: SchedulingSnapshot,
    status: str,
    schedule: list[dict[str, Any]],
    blocked: list[dict[str, str]],
) -> ScheduleCandidate:
    return ScheduleCandidate.model_validate(
        {
            "input_hash": snapshot.input_hash,
            "algorithm_used": "cp_sat",
            "solver_status": status,
            "fallback_used": False,
            "fallback_reason": None,
            "blocked_steps": blocked,
            "schedule": {"steps": schedule},
            "metrics": {
                "scheduled_step_count": len(schedule),
                "blocked_step_count": len(blocked),
                "blocked_step_ids": sorted(item["step_id"] for item in blocked),
            },
        }
    )


def _as_minute(value: Any, as_of: datetime, default: int) -> int:
    minute = _as_optional_minute(value, as_of)
    return minute if minute is not None else default


def _as_optional_minute(value: Any, as_of: datetime) -> int | None:
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return None
    return max(0, int((parsed.astimezone(UTC) - as_of).total_seconds() // 60))


def _timestamp(as_of: datetime, minute: int) -> str:
    value = (as_of + timedelta(minutes=minute)).astimezone(UTC).isoformat()
    return value.replace("+00:00", "Z")


def _as_optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
