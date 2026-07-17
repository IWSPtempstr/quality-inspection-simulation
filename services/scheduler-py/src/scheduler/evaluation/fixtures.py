"""Controlled fixtures used by the offline scheduler evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass

from scheduler.contracts.candidate import FallbackReason
from scheduler.contracts.snapshot import SchedulingSnapshot


@dataclass(frozen=True)
class EvaluationFixture:
    """A controlled snapshot plus the expected evaluation mode."""

    case_id: str
    description: str
    snapshot: SchedulingSnapshot
    fallback_trigger: FallbackReason | None = None
    fallback_status: str | None = None


def suite_fixtures() -> tuple[EvaluationFixture, ...]:
    """Return the ordered S5 fixture suite."""
    return (
        hard_constraints_fixture(),
        frozen_invariance_fixture(),
        fallback_determinism_fixture(),
        equal_sla_change_bias_fixture(),
    )


def hard_constraints_fixture() -> EvaluationFixture:
    return EvaluationFixture(
        case_id="hard_constraints",
        description="Feasible CP-SAT fixture with ordered steps and no hard-rule violations.",
        snapshot=_snapshot(
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
                    [_step("three", employee_ids=["employee-2"])],
                ),
            ],
            resources={
                "equipment": [{"id": "eq-1", "capacity": 2}],
                "employees": [
                    {"id": "employee-1", "skills": ["inspect"]},
                    {"id": "employee-2", "skills": ["inspect"]},
                ],
            },
        ),
    )


def frozen_invariance_fixture() -> EvaluationFixture:
    return EvaluationFixture(
        case_id="frozen_invariance",
        description="Frozen work stays byte-stable across CP-SAT and deterministic fallback.",
        snapshot=_snapshot(
            [
                _order(
                    "order-1",
                    "normal",
                    "2026-07-16T06:00:00Z",
                    [_step("frozen"), _step("next")],
                )
            ],
            frozen_steps=[
                {
                    "id": "frozen",
                    "start": 60,
                    "end": 90,
                    "equipment_id": "eq-1",
                    "employee_id": "employee-1",
                }
            ],
        ),
        fallback_trigger="cp_sat_infeasible",
        fallback_status="infeasible",
    )


def fallback_determinism_fixture() -> EvaluationFixture:
    return EvaluationFixture(
        case_id="fallback_determinism",
        description="Repeated fallback for the same snapshot produces the same candidate hash.",
        snapshot=_snapshot(
            [
                _order("normal", "normal", "2026-07-16T03:00:00Z", [_step("normal-step")]),
                _order("vip", "vip", "2026-07-16T03:00:00Z", [_step("vip-step")]),
            ]
        ),
        fallback_trigger="cp_sat_infeasible",
        fallback_status="infeasible",
    )


def equal_sla_change_bias_fixture() -> EvaluationFixture:
    return EvaluationFixture(
        case_id="equal_sla_change_bias",
        description="Equal-SLA fixture where CP-SAT keeps more formal starts than fallback.",
        snapshot=_snapshot(
            [
                _order(
                    "normal",
                    "normal",
                    "2026-07-16T03:00:00Z",
                    [
                        _step(
                            "normal-step",
                            formal_start="2026-07-16T00:00:00Z",
                        )
                    ],
                ),
                _order(
                    "vip",
                    "vip",
                    "2026-07-16T03:00:00Z",
                    [
                        _step(
                            "vip-step",
                            formal_start="2026-07-16T00:30:00Z",
                        )
                    ],
                ),
            ]
        ),
        fallback_trigger="cp_sat_infeasible",
        fallback_status="infeasible",
    )


def _snapshot(
    orders: list[dict[str, object]],
    *,
    resources: dict[str, object] | None = None,
    frozen_steps: list[dict[str, object]] | None = None,
) -> SchedulingSnapshot:
    return SchedulingSnapshot.model_validate(
        {
            "snapshot_id": "snapshot-s5",
            "input_hash": "sha256:s5",
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
