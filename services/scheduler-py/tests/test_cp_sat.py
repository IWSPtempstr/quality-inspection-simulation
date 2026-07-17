"""Controlled fixture coverage for the S2 CP-SAT projection and hard rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scheduler.contracts.snapshot import SchedulingSnapshot
from scheduler.cp_sat import solve_snapshot


def _snapshot(
    orders: list[dict[str, object]],
    *,
    resources: dict[str, object] | None = None,
    frozen_steps: list[dict[str, object]] | None = None,
) -> SchedulingSnapshot:
    return SchedulingSnapshot.model_validate(
        {
            "snapshot_id": "snapshot-s2",
            "input_hash": "sha256:s2",
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
    order_id: str,
    priority: str,
    promise_at: str,
    steps: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "id": order_id,
        "priority": priority,
        "promise_at": promise_at,
        "steps": steps,
    }


def _step(step_id: str, **values: object) -> dict[str, object]:
    return {
        "id": step_id,
        "duration_minutes": 30,
        "equipment_ids": ["eq-1"],
        "employee_ids": ["employee-1"],
        "required_skill": "inspect",
        **values,
    }


def _steps(candidate: object) -> list[dict[str, object]]:
    return list(candidate.schedule["steps"])


def _minus_minutes(timestamp: object, minutes: int) -> str:
    parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    return (parsed.astimezone(UTC) - timedelta(minutes=minutes)).isoformat().replace(
        "+00:00", "Z"
    )


def test_cp_sat_enforces_order_and_resource_non_overlap() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [
                _order(
                    "order-1",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [_step("one"), _step("two")],
                ),
                _order(
                    "order-2",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [_step("three")],
                ),
            ]
        )
    )

    scheduled = _steps(candidate)
    assert candidate.solver_status in {"optimal", "feasible"}
    assert len(scheduled) == 3
    assert [item["step_id"] for item in scheduled[:2]] == ["one", "two"]
    assert all(scheduled[index]["end"] <= scheduled[index + 1]["start"] for index in range(2))


def test_frozen_step_remains_unchanged_and_blocks_shared_resource() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [_order("order-1", "normal", "2026-07-16T06:00:00Z", [_step("frozen"), _step("next")])],
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

    scheduled = {item["step_id"]: item for item in _steps(candidate)}
    assert scheduled["frozen"]["start"] == "2026-07-16T01:00:00Z"
    assert scheduled["frozen"]["end"] == "2026-07-16T01:30:00Z"
    assert scheduled["next"]["start"] >= scheduled["frozen"]["end"]


def test_weighted_lateness_has_priority_over_normal_order() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [
                _order("normal", "normal", "2026-07-16T00:00:00Z", [_step("normal-step")]),
                _order("vip", "vip", "2026-07-16T00:00:10Z", [_step("vip-step")]),
            ]
        )
    )

    scheduled = {item["step_id"]: item for item in _steps(candidate)}
    assert scheduled["vip-step"]["start"] == "2026-07-16T00:00:00Z"
    assert scheduled["normal-step"]["start"] >= scheduled["vip-step"]["end"]


def test_blockers_and_metrics_include_every_unscheduled_step() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [_order("order-1", "normal", "2026-07-16T01:00:00Z", [_step("blocked")])],
            resources={"equipment": [{"id": "eq-1"}], "employees": []},
        )
    )

    assert candidate.schedule == {"steps": []}
    assert candidate.blocked_steps == ({"step_id": "blocked", "reason": "no_eligible_employee"},)
    assert candidate.metrics["blocked_step_ids"] == ["blocked"]


def test_employee_shift_limits_selected_work_to_the_available_window() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [_order("order-1", "normal", "2026-07-16T06:00:00Z", [_step("shifted")])],
            resources={
                "equipment": [{"id": "eq-1"}],
                "employees": [
                    {
                        "id": "employee-1",
                        "skills": ["inspect"],
                        "shifts": [
                            {
                                "start": "2026-07-16T01:00:00Z",
                                "end": "2026-07-16T02:00:00Z",
                            }
                        ],
                    }
                ],
            },
        )
    )

    scheduled = _steps(candidate)
    assert len(scheduled) == 1
    assert scheduled[0]["start"] == "2026-07-16T01:00:00Z"
    assert scheduled[0]["end"] == "2026-07-16T01:30:00Z"


def test_equipment_maintenance_and_failure_blackouts_are_unavailable() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [_order("order-1", "normal", "2026-07-16T06:00:00Z", [_step("delayed")])],
            resources={
                "equipment": [
                    {
                        "id": "eq-1",
                        "maintenance": [
                            {
                                "start": "2026-07-16T00:00:00Z",
                                "end": "2026-07-16T00:30:00Z",
                            }
                        ],
                        "failures": [
                            {
                                "start": "2026-07-16T00:30:00Z",
                                "end": "2026-07-16T01:00:00Z",
                            }
                        ],
                    }
                ],
                "employees": [{"id": "employee-1", "skills": ["inspect"]}],
            },
        )
    )

    assert _steps(candidate)[0]["start"] == "2026-07-16T01:00:00Z"


def test_equipment_capacity_allows_parallel_work_only_up_to_its_limit() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [
                _order(
                    "order-1",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [_step("one", employee_ids=["employee-1"])],
                ),
                _order(
                    "order-2",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [_step("two", employee_ids=["employee-2"])],
                ),
            ],
            resources={
                "equipment": [{"id": "eq-1", "capacity": 2}],
                "employees": [
                    {"id": "employee-1", "skills": ["inspect"]},
                    {"id": "employee-2", "skills": ["inspect"]},
                ],
            },
        )
    )

    assert {item["start"] for item in _steps(candidate)} == {"2026-07-16T00:00:00Z"}


def test_consumable_exhaustion_blocks_the_later_requirement() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [
                _order(
                    "order-1",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [_step("first", consumables={"reagent": 1})],
                ),
                _order(
                    "order-2",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [_step("second", consumables={"reagent": 1})],
                ),
            ],
            resources={
                "equipment": [{"id": "eq-1"}],
                "employees": [{"id": "employee-1", "skills": ["inspect"]}],
                "consumables": {"reagent": 1},
            },
        )
    )

    assert [item["step_id"] for item in _steps(candidate)] == ["first"]
    assert candidate.blocked_steps == ({"step_id": "second", "reason": "insufficient_consumables"},)


def test_preprocessing_resource_is_an_explicit_non_overlapping_occupancy() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [
                _order(
                    "order-1",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [
                        _step(
                            "one",
                            equipment_ids=["eq-1"],
                            employee_ids=["employee-1"],
                            preprocessing_minutes=30,
                            preprocessing_resource_id="prep-1",
                        )
                    ],
                ),
                _order(
                    "order-2",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [
                        _step(
                            "two",
                            equipment_ids=["eq-2"],
                            employee_ids=["employee-2"],
                            preprocessing_minutes=30,
                            preprocessing_resource_id="prep-1",
                        )
                    ],
                ),
            ],
            resources={
                "equipment": [{"id": "eq-1"}, {"id": "eq-2"}],
                "employees": [
                    {"id": "employee-1", "skills": ["inspect"]},
                    {"id": "employee-2", "skills": ["inspect"]},
                ],
                "preprocessing_resources": [{"id": "prep-1"}],
            },
        )
    )

    starts = [item["start"] for item in _steps(candidate)]
    assert starts == ["2026-07-16T00:00:00Z", "2026-07-16T00:30:00Z"]


def test_transfer_resource_is_an_explicit_non_overlapping_occupancy() -> None:
    candidate = solve_snapshot(
        _snapshot(
            [
                _order(
                    "order-1",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [
                        _step(
                            "one",
                            equipment_ids=["eq-1"],
                            employee_ids=["employee-1"],
                            transfer_minutes=30,
                            transfer_resource_id="transfer-1",
                        )
                    ],
                ),
                _order(
                    "order-2",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [
                        _step(
                            "two",
                            equipment_ids=["eq-2"],
                            employee_ids=["employee-2"],
                            transfer_minutes=30,
                            transfer_resource_id="transfer-1",
                        )
                    ],
                ),
            ],
            resources={
                "equipment": [{"id": "eq-1"}, {"id": "eq-2"}],
                "employees": [
                    {"id": "employee-1", "skills": ["inspect"]},
                    {"id": "employee-2", "skills": ["inspect"]},
                ],
                "transfer_resources": [{"id": "transfer-1"}],
            },
        )
    )

    steps = _steps(candidate)
    transfer_windows = sorted(
        (_minus_minutes(item["end"], 30), item["end"]) for item in steps
    )
    assert transfer_windows == [
        ("2026-07-16T00:30:00Z", "2026-07-16T01:00:00Z"),
        ("2026-07-16T01:00:00Z", "2026-07-16T01:30:00Z"),
    ]
