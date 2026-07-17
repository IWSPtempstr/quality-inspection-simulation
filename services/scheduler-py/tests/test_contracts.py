"""S1 contract tests: only validation and pure hashing behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scheduler.conf.settings import SchedulerSettings
from scheduler.contracts.candidate import ScheduleCandidate
from scheduler.contracts.snapshot import SchedulingSnapshot
from scheduler.core.canonical_json import normalized_candidate


def snapshot_payload() -> dict[str, object]:
    return {
        "snapshot_id": "snapshot-1",
        "input_hash": "sha256:input",
        "as_of": "2026-07-16T08:00:00+08:00",
        "base_schedule_version": 4,
        "resource_snapshot_version": 7,
        "orders": [{"id": "order-1", "priority": 1}],
        "resources": {"equipment": [{"id": "machine-1"}]},
        "frozen_steps": [{"id": "step-1"}],
    }


def candidate_payload() -> dict[str, object]:
    return {
        "input_hash": "sha256:input",
        "algorithm_used": "cp_sat",
        "solver_status": "feasible",
        "fallback_used": False,
        "fallback_reason": None,
        "blocked_steps": [],
        "schedule": {"steps": [{"id": "step-1", "start": "2026-07-16T00:00:00Z"}]},
        "metrics": {"changes": 1},
    }


def test_snapshot_rejects_naive_datetime() -> None:
    payload = snapshot_payload()
    payload["as_of"] = "2026-07-16T08:00:00"

    with pytest.raises(ValidationError, match="timezone"):
        SchedulingSnapshot.model_validate(payload)


def test_snapshot_rejects_unknown_top_level_field() -> None:
    payload = snapshot_payload()
    payload["untrusted_instruction"] = "create an order"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SchedulingSnapshot.model_validate(payload)


@pytest.mark.parametrize(
    ("fallback_used", "fallback_reason"),
    [(True, None), (False, "cp_sat_execution_error")],
)
def test_candidate_rejects_invalid_fallback_combinations(
    fallback_used: bool, fallback_reason: object
) -> None:
    payload = candidate_payload()
    payload["fallback_used"] = fallback_used
    payload["fallback_reason"] = fallback_reason

    with pytest.raises(ValidationError):
        ScheduleCandidate.model_validate(payload)


def test_settings_reject_invalid_production_configuration() -> None:
    with pytest.raises(ValidationError, match="production requires"):
        SchedulerSettings(environment="production")
    with pytest.raises(ValidationError):
        SchedulerSettings(solver_time_limit_seconds=0)


def test_hash_is_stable_across_dictionary_key_order() -> None:
    first = ScheduleCandidate.model_validate(candidate_payload())
    reordered = candidate_payload()
    reordered["schedule"] = {
        "steps": [{"start": "2026-07-16T08:00:00+08:00", "id": "step-1"}]
    }
    second = ScheduleCandidate.model_validate(reordered)

    assert (
        normalized_candidate(first).normalized_result_hash
        == normalized_candidate(second).normalized_result_hash
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"input_hash": "sha256:other-input"},
        {"schedule": {"steps": [{"id": "step-2", "start": "2026-07-16T00:00:00Z"}]}},
        {"blocked_steps": [{"id": "blocked-step"}]},
        {"metrics": {"changes": 2}},
        {
            "algorithm_used": "sla_fallback",
            "fallback_used": True,
            "fallback_reason": "cp_sat_execution_error",
        },
        {"schedule": {"steps": [{"id": "step-1", "start": "2026-07-16T00:00:01Z"}]}},
    ],
)
def test_hash_changes_when_contractual_content_changes(patch: dict[str, object]) -> None:
    first = ScheduleCandidate.model_validate(candidate_payload())
    changed = candidate_payload()
    changed.update(patch)
    second = ScheduleCandidate.model_validate(changed)

    assert (
        normalized_candidate(first).normalized_result_hash
        != normalized_candidate(second).normalized_result_hash
    )


def test_s1_modules_do_not_import_later_phase_dependencies() -> None:
    source_root = Path(__file__).parents[1] / "src" / "scheduler"
    s1_roots = ("conf", "contracts", "core", "entities")
    forbidden = (
        "fastapi",
        "ortools",
        "httpx",
        "pika",
        "aio_pika",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "redis",
    )

    for root in s1_roots:
        for module in (source_root / root).rglob("*.py"):
            source = module.read_text(encoding="utf-8").lower()
            assert all(
                f"import {dependency}" not in source for dependency in forbidden
            ), module
