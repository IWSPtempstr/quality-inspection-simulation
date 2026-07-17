"""Regression tests for the S5 controlled-fixture scheduler harness."""

from scheduler.evaluation.fixtures import (
    equal_sla_change_bias_fixture,
    frozen_invariance_fixture,
    hard_constraints_fixture,
)
from scheduler.evaluation.harness import evaluate_candidate, run_case, run_suite
from scheduler.sla_fallback import build_fallback_candidate


def test_controlled_suite_has_zero_hard_constraint_violations() -> None:
    suite = run_suite()

    assert suite.cases
    assert all(not case.metrics.hard_constraint_violations for case in suite.cases)


def test_frozen_step_invariance_holds_for_cp_sat_and_fallback() -> None:
    fixture = frozen_invariance_fixture()
    cp_sat_result = run_case(
        fixture.__class__(fixture.case_id, fixture.description, fixture.snapshot)
    )
    fallback = build_fallback_candidate(
        fixture.snapshot,
        trigger="cp_sat_infeasible",
        cp_sat_status="infeasible",
    )
    fallback_metrics = evaluate_candidate(fixture.snapshot, fallback)

    assert not cp_sat_result.metrics.frozen_step_violations
    assert not fallback_metrics.frozen_step_violations


def test_fallback_is_repeatable_for_the_same_snapshot() -> None:
    suite = run_suite()

    assert suite.fallback_replay_hashes[0] == suite.fallback_replay_hashes[1]


def test_feasible_cp_sat_case_never_uses_fallback() -> None:
    result = run_case(hard_constraints_fixture())

    assert result.algorithm_used == "cp_sat"
    assert result.solver_status in {"feasible", "optimal"}
    assert result.fallback_used is False


def test_cp_sat_keeps_fewer_changes_when_sla_is_equal() -> None:
    fixture = equal_sla_change_bias_fixture()
    cp_sat_result = run_case(
        fixture.__class__(fixture.case_id, fixture.description, fixture.snapshot)
    )
    fallback = build_fallback_candidate(
        fixture.snapshot,
        trigger="cp_sat_infeasible",
        cp_sat_status="infeasible",
    )
    fallback_metrics = evaluate_candidate(fixture.snapshot, fallback)

    assert cp_sat_result.metrics.weighted_late_minutes == fallback_metrics.weighted_late_minutes
    assert cp_sat_result.metrics.late_minutes == fallback_metrics.late_minutes
    assert cp_sat_result.metrics.change_count < fallback_metrics.change_count
