"""Controlled-fixture tests for the deterministic S3 SLA fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from scheduler.contracts.snapshot import SchedulingSnapshot
from scheduler.core.canonical_json import normalized_candidate
from scheduler.sla_fallback import FallbackRejectedError, build_fallback_candidate


def _snapshot(
    orders: list[dict[str, object]],
    *,
    resources: dict[str, object] | None = None,
    frozen_steps: list[dict[str, object]] | None = None,
) -> SchedulingSnapshot:
    return SchedulingSnapshot.model_validate(
        {
            "snapshot_id": "snapshot-s3",
            "input_hash": "sha256:s3",
            "as_of": "2026-07-16T00:00:00Z",
            "base_schedule_version": 1,
            "resource_snapshot_version": 1,
            "orders": orders,
            "resources": resources
            or {
                "equipment": [{"id": "eq-1"}],
                "employees": [{"id": "employee-1", "skills": ["inspect"]}],
            },
            "frozen_steps": frozen_steps or [],
        }
    )


def _order(
    order_id: str, priority: str, promise_at: str, steps: list[dict[str, object]]
) -> dict[str, object]:
    return {"id": order_id, "priority": priority, "promise_at": promise_at, "steps": steps}


def _step(step_id: str, **values: object) -> dict[str, object]:
    return {
        "id": step_id,
        "duration_minutes": 30,
        "equipment_ids": ["eq-1"],
        "employee_ids": ["employee-1"],
        "required_skill": "inspect",
        **values,
    }


def _fallback(snapshot: SchedulingSnapshot, **kwargs: object):
    return build_fallback_candidate(
        snapshot,
        trigger="cp_sat_infeasible",
        cp_sat_status="infeasible",
        **kwargs,
    )


def test_fallback_is_byte_equivalent_for_same_snapshot_and_trigger() -> None:
    snapshot = _snapshot(
        [
            _order("normal", "normal", "2026-07-16T03:00:00Z", [_step("normal-step")]),
            _order("vip", "vip", "2026-07-16T03:00:00Z", [_step("vip-step")]),
        ]
    )

    first, second = _fallback(snapshot), _fallback(snapshot)

    assert first == second
    assert (
        normalized_candidate(first).normalized_result_hash
        == normalized_candidate(second).normalized_result_hash
    )
    assert [item["step_id"] for item in first.schedule["steps"]] == ["vip-step", "normal-step"]


def test_overdue_orders_sort_before_non_overdue_orders() -> None:
    candidate = _fallback(
        _snapshot(
            [
                _order("future", "vip", "2026-07-16T03:00:00Z", [_step("future-step")]),
                _order("overdue", "normal", "2026-07-15T23:00:00Z", [_step("overdue-step")]),
            ]
        )
    )

    assert [item["step_id"] for item in candidate.schedule["steps"]] == [
        "overdue-step",
        "future-step",
    ]


@pytest.mark.parametrize("status", ["feasible", "optimal"])
def test_feasible_or_optimal_cp_sat_result_cannot_trigger_fallback(status: str) -> None:
    with pytest.raises(FallbackRejectedError, match="cannot use fallback"):
        build_fallback_candidate(_snapshot([]), trigger="cp_sat_infeasible", cp_sat_status=status)


def test_only_declared_failure_status_can_authorize_trigger() -> None:
    snapshot = _snapshot([_order("order", "normal", "2026-07-16T03:00:00Z", [_step("step")])])

    with pytest.raises(FallbackRejectedError):
        build_fallback_candidate(
            snapshot,
            trigger="cp_sat_timeout_without_feasible_solution",
            cp_sat_status="infeasible",
        )
    with pytest.raises(FallbackRejectedError):
        build_fallback_candidate(
            snapshot,
            trigger="input_size_protection_threshold_exceeded",
            cp_sat_status="unknown",
            input_size_limit=1,
        )
    candidate = build_fallback_candidate(
        snapshot,
        trigger="cp_sat_timeout_without_feasible_solution",
        cp_sat_status="unknown",
    )
    assert candidate.fallback_reason == "cp_sat_timeout_without_feasible_solution"


@pytest.mark.parametrize(
    ("trigger", "status", "limit"),
    [
        ("cp_sat_infeasible", "infeasible", None),
        ("cp_sat_timeout_without_feasible_solution", "unknown", None),
        ("cp_sat_execution_error", "execution_error", None),
        ("input_size_protection_threshold_exceeded", "unknown", 1),
    ],
)
def test_each_declared_non_feasible_trigger_is_explicit(
    trigger: str, status: str, limit: int | None
) -> None:
    steps = [_step("step")]
    if trigger == "input_size_protection_threshold_exceeded":
        steps.append(_step("step-two"))
    snapshot = _snapshot([_order("order", "normal", "2026-07-16T03:00:00Z", steps)])

    candidate = build_fallback_candidate(
        snapshot,
        trigger=trigger,  # type: ignore[arg-type]
        cp_sat_status=status,
        input_size_limit=limit,
    )

    assert candidate.fallback_reason == trigger


def test_sla_fallback_has_no_ortools_dependency() -> None:
    module = Path(__file__).parents[1] / "src" / "scheduler" / "sla_fallback" / "fallback.py"

    assert "ortools" not in module.read_text(encoding="utf-8").lower()


def test_frozen_work_is_preserved_and_shared_resources_do_not_overlap() -> None:
    candidate = _fallback(
        _snapshot(
            [_order("order", "normal", "2026-07-16T03:00:00Z", [_step("frozen"), _step("next")])],
            frozen_steps=[
                {
                    "id": "frozen",
                    "start": 60,
                    "end": 90,
                    "equipment_id": "eq-1",
                    "employee_id": "employee-1",
                }
            ],
        )
    )

    scheduled = {item["step_id"]: item for item in candidate.schedule["steps"]}
    assert scheduled["frozen"]["start"] == "2026-07-16T01:00:00Z"
    assert scheduled["frozen"]["end"] == "2026-07-16T01:30:00Z"
    assert scheduled["next"]["start"] >= scheduled["frozen"]["end"]


def test_frozen_resource_window_is_reserved_before_earlier_greedy_assignment() -> None:
    candidate = _fallback(
        _snapshot(
            [
                _order("first", "normal", "2026-07-16T04:00:00Z", [_step("first-step")]),
                _order("second", "normal", "2026-07-16T04:00:00Z", [_step("frozen-step")]),
            ],
            frozen_steps=[
                {
                    "id": "frozen-step",
                    "start": 0,
                    "end": 30,
                    "equipment_id": "eq-1",
                    "employee_id": "employee-1",
                }
            ],
        )
    )

    scheduled = {item["step_id"]: item for item in candidate.schedule["steps"]}
    assert scheduled["first-step"]["start"] == "2026-07-16T00:30:00Z"


def test_hard_resource_rules_block_or_delay_work() -> None:
    candidate = _fallback(
        _snapshot(
            [
                _order(
                    "first",
                    "urgent",
                    "2026-07-16T04:00:00Z",
                    [_step("first", consumables={"kit": 1})],
                ),
                _order(
                    "second",
                    "normal",
                    "2026-07-16T04:00:00Z",
                    [_step("second", consumables={"kit": 1})],
                ),
            ],
            resources={
                "equipment": [
                    {
                        "id": "eq-1",
                        "maintenance": [
                            {"start": "2026-07-16T00:00:00Z", "end": "2026-07-16T00:30:00Z"}
                        ],
                    }
                ],
                "employees": [
                    {
                        "id": "employee-1",
                        "skills": ["inspect"],
                        "shifts": [
                            {"start": "2026-07-16T00:30:00Z", "end": "2026-07-16T02:00:00Z"}
                        ],
                    }
                ],
                "consumables": {"kit": 1},
            },
        )
    )

    assert candidate.schedule["steps"][0]["start"] == "2026-07-16T00:30:00Z"
    assert candidate.blocked_steps == ({"step_id": "second", "reason": "insufficient_consumables"},)
