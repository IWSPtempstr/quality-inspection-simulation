"""Offline controlled-fixture harness for S5 scheduler validation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypedDict

from scheduler.contracts.candidate import ScheduleCandidate
from scheduler.contracts.snapshot import SchedulingSnapshot
from scheduler.core.canonical_json import normalized_candidate
from scheduler.cp_sat import solve_snapshot
from scheduler.evaluation.fixtures import EvaluationFixture, suite_fixtures
from scheduler.sla_fallback import build_fallback_candidate

_PRIORITY_WEIGHT = {"vip": 100, "urgent": 10, "normal": 1}


class StepRecord(TypedDict):
    order_id: str
    equipment_ids: tuple[str, ...]
    employee_ids: tuple[str, ...]
    required_skill: str | None
    required_role: str | None
    formal_start: int | None


class OrderRecord(TypedDict):
    promise_at: int
    weight: int


class AssignmentRecord(TypedDict):
    step_id: str
    order_id: str
    start: int
    end: int
    equipment_id: str
    employee_id: str
    frozen: bool


@dataclass(frozen=True)
class EvaluationMetrics:
    """Derived correctness and stability metrics for one candidate."""

    hard_constraint_violations: tuple[str, ...]
    frozen_step_violations: tuple[str, ...]
    late_order_count: int
    late_minutes: int
    weighted_late_minutes: int
    change_count: int


@dataclass(frozen=True)
class EvaluationCaseResult:
    """One harness execution plus its derived metrics."""

    case_id: str
    algorithm_used: str
    fallback_used: bool
    solver_status: str
    normalized_result_hash: str
    metrics: EvaluationMetrics
    candidate: ScheduleCandidate


@dataclass(frozen=True)
class EvaluationSuiteResult:
    """Collected S5 evidence across the controlled suite."""

    cases: tuple[EvaluationCaseResult, ...]
    fallback_replay_hashes: tuple[str, str]
    feasible_case_used_fallback: bool
    equal_sla_weighted_lateness: tuple[int, int]
    equal_sla_change_counts: tuple[int, int]


def run_case(fixture: EvaluationFixture) -> EvaluationCaseResult:
    """Execute one fixture using the mode declared by the fixture."""
    candidate = _candidate_for_fixture(fixture)
    return _result_for_candidate(fixture.case_id, fixture.snapshot, candidate)


def run_suite() -> EvaluationSuiteResult:
    """Execute the full S5 controlled-fixture suite."""
    fixtures = suite_fixtures()
    case_results = tuple(run_case(fixture) for fixture in fixtures)

    fallback_fixture = _fixture_by_id(fixtures, "fallback_determinism")
    first_fallback = _fallback_candidate(fallback_fixture)
    second_fallback = _fallback_candidate(fallback_fixture)

    feasible_fixture = _fixture_by_id(fixtures, "hard_constraints")
    feasible_result = _result_for_candidate(
        feasible_fixture.case_id,
        feasible_fixture.snapshot,
        solve_snapshot(feasible_fixture.snapshot),
    )

    equal_fixture = _fixture_by_id(fixtures, "equal_sla_change_bias")
    cp_sat_result = _result_for_candidate(
        equal_fixture.case_id,
        equal_fixture.snapshot,
        solve_snapshot(equal_fixture.snapshot),
    )
    fallback_result = _result_for_candidate(
        equal_fixture.case_id,
        equal_fixture.snapshot,
        _fallback_candidate(equal_fixture),
    )

    return EvaluationSuiteResult(
        cases=case_results,
        fallback_replay_hashes=(
            normalized_candidate(first_fallback).normalized_result_hash,
            normalized_candidate(second_fallback).normalized_result_hash,
        ),
        feasible_case_used_fallback=feasible_result.fallback_used,
        equal_sla_weighted_lateness=(
            cp_sat_result.metrics.weighted_late_minutes,
            fallback_result.metrics.weighted_late_minutes,
        ),
        equal_sla_change_counts=(
            cp_sat_result.metrics.change_count,
            fallback_result.metrics.change_count,
        ),
    )


def evaluate_candidate(
    snapshot: SchedulingSnapshot, candidate: ScheduleCandidate
) -> EvaluationMetrics:
    """Validate controlled hard rules and derive comparison metrics."""
    steps = _step_index(snapshot)
    assignments = _assignment_index(candidate)
    equipment = _resource_index(snapshot.resources.get("equipment"))
    employees = _resource_index(snapshot.resources.get("employees"))
    violations: list[str] = []

    for step_id, assignment in assignments.items():
        step = steps.get(step_id)
        if step is None:
            violations.append(f"unknown_step:{step_id}")
            continue
        if assignment["end"] <= assignment["start"]:
            violations.append(f"non_positive_duration:{step_id}")
        if assignment["order_id"] != step["order_id"]:
            violations.append(f"wrong_order:{step_id}")
        if assignment["equipment_id"] not in step["equipment_ids"]:
            violations.append(f"wrong_equipment:{step_id}")
        if assignment["employee_id"] not in step["employee_ids"]:
            violations.append(f"wrong_employee:{step_id}")
        if not _employee_matches(
            employees.get(assignment["employee_id"]),
            step["required_skill"],
            step["required_role"],
        ):
            violations.append(f"ineligible_employee:{step_id}")
        if not _within_employee_shift(
            employees.get(assignment["employee_id"]),
            assignment["start"],
            assignment["end"],
            snapshot.as_of,
        ):
            violations.append(f"outside_shift:{step_id}")
        if _overlaps_blackout(
            equipment.get(assignment["equipment_id"]),
            assignment["start"],
            assignment["end"],
            snapshot.as_of,
            ("maintenance", "failures"),
        ):
            violations.append(f"equipment_blackout_overlap:{step_id}")
        if _overlaps_blackout(
            employees.get(assignment["employee_id"]),
            assignment["start"],
            assignment["end"],
            snapshot.as_of,
            ("unavailability",),
        ):
            violations.append(f"employee_unavailable:{step_id}")

    for order in snapshot.orders:
        prior_end: int | None = None
        for raw_step in _records(order.get("steps")):
            scheduled_step = assignments.get(str(raw_step["id"]))
            if scheduled_step is None:
                continue
            if prior_end is not None and scheduled_step["start"] < prior_end:
                violations.append(f"precedence:{raw_step['id']}")
            prior_end = scheduled_step["end"]

    equipment_windows: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for assignment in assignments.values():
        equipment_windows[assignment["equipment_id"]].append(
            (assignment["start"], assignment["end"])
        )
    for equipment_id, windows in equipment_windows.items():
        resource = equipment.get(equipment_id, {})
        capacity = _int_value(resource.get("capacity"), default=1)
        if _max_concurrency(windows) > capacity:
            violations.append(f"equipment_capacity:{equipment_id}")

    employee_windows: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for assignment in assignments.values():
        employee_windows[assignment["employee_id"]].append(
            (assignment["start"], assignment["end"])
        )
    for employee_id, windows in employee_windows.items():
        if _max_concurrency(windows) > 1:
            violations.append(f"employee_overlap:{employee_id}")

    frozen_violations = _frozen_step_violations(snapshot, assignments)
    late_order_count, late_minutes, weighted_late_minutes = _lateness(snapshot, assignments)
    return EvaluationMetrics(
        hard_constraint_violations=tuple(sorted(set(violations))),
        frozen_step_violations=frozen_violations,
        late_order_count=late_order_count,
        late_minutes=late_minutes,
        weighted_late_minutes=weighted_late_minutes,
        change_count=_change_count(snapshot, assignments),
    )


def _result_for_candidate(
    case_id: str, snapshot: SchedulingSnapshot, candidate: ScheduleCandidate
) -> EvaluationCaseResult:
    normalized = normalized_candidate(candidate)
    return EvaluationCaseResult(
        case_id=case_id,
        algorithm_used=candidate.algorithm_used,
        fallback_used=candidate.fallback_used,
        solver_status=candidate.solver_status,
        normalized_result_hash=normalized.normalized_result_hash,
        metrics=evaluate_candidate(snapshot, candidate),
        candidate=candidate,
    )


def _fixture_by_id(
    fixtures: tuple[EvaluationFixture, ...], case_id: str
) -> EvaluationFixture:
    for fixture in fixtures:
        if fixture.case_id == case_id:
            return fixture
    raise ValueError(f"unknown fixture {case_id}")


def _candidate_for_fixture(fixture: EvaluationFixture) -> ScheduleCandidate:
    if fixture.fallback_trigger is None or fixture.fallback_status is None:
        return solve_snapshot(fixture.snapshot)
    return _fallback_candidate(fixture)


def _fallback_candidate(fixture: EvaluationFixture) -> ScheduleCandidate:
    trigger = fixture.fallback_trigger
    status = fixture.fallback_status
    if trigger is None or status is None:
        raise ValueError(f"fixture {fixture.case_id} does not declare fallback mode")
    return build_fallback_candidate(
        fixture.snapshot,
        trigger=trigger,
        cp_sat_status=status,
    )


def _step_index(snapshot: SchedulingSnapshot) -> dict[str, StepRecord]:
    result: dict[str, StepRecord] = {}
    for order in snapshot.orders:
        order_id = str(order["id"])
        for raw_step in _records(order.get("steps")):
            result[str(raw_step["id"])] = StepRecord(
                order_id=order_id,
                equipment_ids=_string_tuple(raw_step.get("equipment_ids")),
                employee_ids=_string_tuple(raw_step.get("employee_ids")),
                required_skill=_optional_string(raw_step.get("required_skill")),
                required_role=_optional_string(raw_step.get("required_role")),
                formal_start=_optional_minute(raw_step.get("formal_start"), snapshot.as_of),
            )
    return result


def _order_index(snapshot: SchedulingSnapshot) -> dict[str, OrderRecord]:
    result: dict[str, OrderRecord] = {}
    for order in snapshot.orders:
        result[str(order["id"])] = OrderRecord(
            promise_at=_minute(order.get("promise_at"), snapshot.as_of),
            weight=_PRIORITY_WEIGHT.get(str(order.get("priority", "normal")).lower(), 1),
        )
    return result


def _assignment_index(candidate: ScheduleCandidate) -> dict[str, AssignmentRecord]:
    result: dict[str, AssignmentRecord] = {}
    for raw in _records(candidate.schedule.get("steps")):
        step_id = str(raw["step_id"])
        result[step_id] = AssignmentRecord(
            step_id=step_id,
            order_id=str(raw["order_id"]),
            start=_timestamp_to_minute(raw["start"]),
            end=_timestamp_to_minute(raw["end"]),
            equipment_id=str(raw["equipment_id"]),
            employee_id=str(raw["employee_id"]),
            frozen=bool(raw.get("frozen", False)),
        )
    return result


def _resource_index(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item["id"]): item
        for item in value
        if isinstance(item, dict) and "id" in item
    }


def _frozen_step_violations(
    snapshot: SchedulingSnapshot, assignments: dict[str, AssignmentRecord]
) -> tuple[str, ...]:
    violations: list[str] = []
    for frozen in snapshot.frozen_steps:
        step_id = str(frozen["id"])
        assignment = assignments.get(step_id)
        if assignment is None:
            violations.append(f"missing_frozen:{step_id}")
            continue
        expected = (
            _int_value(frozen["start"]),
            _int_value(frozen["end"]),
            str(frozen["equipment_id"]),
            str(frozen["employee_id"]),
        )
        actual = (
            assignment["start"],
            assignment["end"],
            assignment["equipment_id"],
            assignment["employee_id"],
        )
        if expected != actual:
            violations.append(f"frozen_changed:{step_id}")
    return tuple(sorted(violations))


def _lateness(
    snapshot: SchedulingSnapshot, assignments: dict[str, AssignmentRecord]
) -> tuple[int, int, int]:
    orders = _order_index(snapshot)
    latest_end_by_order: dict[str, int] = {}
    for assignment in assignments.values():
        order_id = assignment["order_id"]
        latest_end = latest_end_by_order.get(order_id, 0)
        latest_end_by_order[order_id] = max(latest_end, assignment["end"])
    late_order_count = 0
    late_minutes = 0
    weighted_late_minutes = 0
    for order_id, latest_end in latest_end_by_order.items():
        promise_at = orders[order_id]["promise_at"]
        lateness = max(0, latest_end - promise_at)
        if lateness > 0:
            late_order_count += 1
        late_minutes += lateness
        weighted_late_minutes += lateness * orders[order_id]["weight"]
    return late_order_count, late_minutes, weighted_late_minutes


def _change_count(snapshot: SchedulingSnapshot, assignments: dict[str, AssignmentRecord]) -> int:
    steps = _step_index(snapshot)
    count = 0
    for step_id, assignment in assignments.items():
        step = steps.get(step_id)
        if step is None:
            continue
        formal_start = step["formal_start"]
        if formal_start is None or assignment["frozen"]:
            continue
        if assignment["start"] != formal_start:
            count += 1
    return count


def _employee_matches(
    employee: dict[str, object] | None,
    required_skill: str | None,
    required_role: str | None,
) -> bool:
    if employee is None:
        return False
    skills = set(_string_tuple(employee.get("skills")))
    roles = set(_string_tuple(employee.get("roles")))
    return (required_skill is None or required_skill in skills) and (
        required_role is None or required_role in roles
    )


def _within_employee_shift(
    employee: dict[str, object] | None,
    start: int,
    end: int,
    as_of: datetime,
) -> bool:
    if employee is None:
        return False
    shifts = _records(employee.get("shifts"))
    if not shifts:
        return True
    for shift in shifts:
        shift_start = _timestamp_to_minute(shift["start"], as_of)
        shift_end = _timestamp_to_minute(shift["end"], as_of)
        if start >= shift_start and end <= shift_end:
            return True
    return False


def _overlaps_blackout(
    resource: dict[str, object] | None,
    start: int,
    end: int,
    as_of: datetime,
    fields: tuple[str, ...],
) -> bool:
    if resource is None:
        return False
    for field in fields:
        for window in _records(resource.get(field)):
            window_start = _timestamp_to_minute(window["start"], as_of)
            window_end = _timestamp_to_minute(window["end"], as_of)
            if _overlap((start, end), (window_start, window_end)):
                return True
    return False


def _max_concurrency(windows: list[tuple[int, int]]) -> int:
    if not windows:
        return 0
    marks: list[tuple[int, int]] = []
    for start, end in windows:
        marks.append((start, 1))
        marks.append((end, -1))
    concurrent = 0
    maximum = 0
    for _, delta in sorted(marks, key=lambda item: (item[0], item[1])):
        concurrent += delta
        maximum = max(maximum, concurrent)
    return maximum


def _overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _records(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _optional_string(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _optional_minute(value: object, as_of: datetime) -> int | None:
    if value is None:
        return None
    return _timestamp_to_minute(value, as_of)


def _minute(value: object, as_of: datetime) -> int:
    return _timestamp_to_minute(value, as_of)


def _int_value(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    return default


def _timestamp_to_minute(value: object, as_of: datetime | None = None) -> int:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    if as_of is not None:
        baseline = as_of.astimezone(UTC)
    else:
        baseline = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((parsed - baseline).total_seconds() // 60)
