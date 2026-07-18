from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from scheduler.api.schemas import ScheduleSubmission
from scheduler.conf.settings import SchedulerSettings
from scheduler.contracts.candidate import ScheduleCandidate
from scheduler.contracts.snapshot import SchedulingSnapshot
from scheduler.core.canonical_json import normalized_candidate
from scheduler.worker.runner import InProcessSchedulerWorker


def build_snapshot(step_count: int, *, snapshot_id: str) -> SchedulingSnapshot:
    steps = [
        {
            "id": f"step-{index}",
            "duration_minutes": 30,
            "equipment_ids": ["eq-1"],
            "employee_ids": ["employee-1"],
            "required_skill": "inspect",
        }
        for index in range(step_count)
    ]
    return SchedulingSnapshot.model_validate(
        {
            "snapshot_id": snapshot_id,
            "input_hash": f"sha256:{snapshot_id}",
            "as_of": "2026-07-17T09:00:00Z",
            "base_schedule_version": 1,
            "resource_snapshot_version": 1,
            "orders": [
                {
                    "id": "order-1",
                    "priority": "normal",
                    "promise_at": "2026-07-17T18:00:00Z",
                    "steps": steps,
                }
            ],
            "resources": {
                "equipment": [{"id": "eq-1"}],
                "employees": [{"id": "employee-1", "skills": ["inspect"]}],
            },
            "frozen_steps": [],
        }
    )


def build_submission(step_count: int, *, preview_id: str, snapshot_id: str) -> ScheduleSubmission:
    return ScheduleSubmission.model_validate(
        {
            "preview_id": preview_id,
            "preview_version": 1,
            "snapshot": build_snapshot(step_count, snapshot_id=snapshot_id).model_dump(mode="json"),
        }
    )


def optimal_candidate(input_hash: str) -> ScheduleCandidate:
    return ScheduleCandidate.model_validate(
        {
            "input_hash": input_hash,
            "algorithm_used": "cp_sat",
            "solver_status": "optimal",
            "fallback_used": False,
            "fallback_reason": None,
            "blocked_steps": [],
            "schedule": {
                "steps": [
                    {
                        "id": "scheduled-step-1",
                        "order_id": "order-1",
                        "project_id": "project-1",
                        "starts_at": "2026-07-17T10:00:00Z",
                        "ends_at": "2026-07-17T10:30:00Z",
                    }
                ]
            },
            "metrics": {"scheduled_step_count": 1},
        }
    )


@dataclass
class RecordingCallback:
    submissions: list[dict[str, Any]]

    def submit_candidate(
        self,
        *,
        preview_id: str,
        preview_version: int,
        snapshot_id: str,
        input_hash: str,
        normalized_result_hash: str,
        candidate: ScheduleCandidate,
    ) -> None:
        self.submissions.append(
            {
                "preview_id": preview_id,
                "preview_version": preview_version,
                "snapshot_id": snapshot_id,
                "input_hash": input_hash,
                "normalized_result_hash": normalized_result_hash,
                "candidate": candidate,
            }
        )


def expect_production_config_validation() -> None:
    try:
        SchedulerSettings(environment="production")
    except ValidationError:
        return
    raise AssertionError("production configuration unexpectedly accepted missing scheduler credentials")


def verify_queue_size_protection_and_deterministic_fallback() -> dict[str, Any]:
    settings = SchedulerSettings(
        environment="test",
        service_bearer_token="ingress-token",
        callback_service_token="callback-token",
        callback_base_url="http://callback.internal",
        queue_size_protection_limit=2,
        solver_time_limit_seconds=17,
    )
    submission = build_submission(3, preview_id="preview-oversized", snapshot_id="snapshot-oversized")
    callback = RecordingCallback(submissions=[])
    worker = InProcessSchedulerWorker(
        settings,
        callback_client=callback,
        solver=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("solver should not run")),
    )
    first = worker._candidate_for(submission)
    second = worker._candidate_for(submission)
    first_hash = normalized_candidate(first).normalized_result_hash
    second_hash = normalized_candidate(second).normalized_result_hash
    if first_hash != second_hash:
        raise AssertionError("oversized snapshot fallback is not deterministic")
    if first.fallback_reason != "input_size_protection_threshold_exceeded":
        raise AssertionError(f"unexpected fallback reason {first.fallback_reason}")
    if not first.fallback_used or first.algorithm_used != "sla_fallback":
        raise AssertionError("oversized snapshot did not use SLA fallback")
    return {
        "queue_size_protection_limit": settings.queue_size_protection_limit,
        "oversized_step_count": 3,
        "fallback_reason": first.fallback_reason,
        "deterministic_hash": first_hash,
    }


def verify_solver_time_limit_is_forwarded() -> dict[str, Any]:
    observed: list[int] = []

    def solver(snapshot: SchedulingSnapshot, *, time_limit_seconds: int) -> ScheduleCandidate:
        observed.append(time_limit_seconds)
        return optimal_candidate(snapshot.input_hash)

    settings = SchedulerSettings(
        environment="test",
        service_bearer_token="ingress-token",
        callback_service_token="callback-token",
        callback_base_url="http://callback.internal",
        queue_size_protection_limit=10,
        solver_time_limit_seconds=17,
    )
    worker = InProcessSchedulerWorker(settings, callback_client=RecordingCallback(submissions=[]), solver=solver)
    submission = build_submission(1, preview_id="preview-time-limit", snapshot_id="snapshot-time-limit")
    candidate = worker._candidate_for(submission)
    if observed != [17]:
        raise AssertionError(f"solver time limit not forwarded: {observed}")
    if candidate.solver_status != "optimal":
        raise AssertionError(f"unexpected candidate status {candidate.solver_status}")
    return {"solver_time_limit_seconds": observed[0], "algorithm_used": candidate.algorithm_used}


def verify_timeout_and_execution_error_fallbacks() -> dict[str, Any]:
    unknown_status_candidate = ScheduleCandidate.model_validate(
        {
            "input_hash": "sha256:snapshot-timeout",
            "algorithm_used": "cp_sat",
            "solver_status": "unknown",
            "fallback_used": False,
            "fallback_reason": None,
            "blocked_steps": [],
            "schedule": {"steps": []},
            "metrics": {"scheduled_step_count": 0},
        }
    )

    timeout_worker = InProcessSchedulerWorker(
        SchedulerSettings(
            environment="test",
            service_bearer_token="ingress-token",
            callback_service_token="callback-token",
            callback_base_url="http://callback.internal",
        ),
        callback_client=RecordingCallback(submissions=[]),
        solver=lambda snapshot, *, time_limit_seconds: unknown_status_candidate,
    )
    timeout_candidate = timeout_worker._candidate_for(
        build_submission(1, preview_id="preview-timeout", snapshot_id="snapshot-timeout")
    )
    if timeout_candidate.fallback_reason != "cp_sat_timeout_without_feasible_solution":
        raise AssertionError(f"unexpected timeout fallback {timeout_candidate.fallback_reason}")

    error_worker = InProcessSchedulerWorker(
        SchedulerSettings(
            environment="test",
            service_bearer_token="ingress-token",
            callback_service_token="callback-token",
            callback_base_url="http://callback.internal",
        ),
        callback_client=RecordingCallback(submissions=[]),
        solver=lambda snapshot, *, time_limit_seconds: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    error_candidate = error_worker._candidate_for(
        build_submission(1, preview_id="preview-error", snapshot_id="snapshot-error")
    )
    if error_candidate.fallback_reason != "cp_sat_execution_error":
        raise AssertionError(f"unexpected execution fallback {error_candidate.fallback_reason}")

    return {
        "timeout_fallback_reason": timeout_candidate.fallback_reason,
        "execution_error_fallback_reason": error_candidate.fallback_reason,
    }


def verify_async_submission_uses_callback() -> dict[str, Any]:
    settings = SchedulerSettings(
        environment="test",
        service_bearer_token="ingress-token",
        callback_service_token="callback-token",
        callback_base_url="http://callback.internal",
    )
    callback = RecordingCallback(submissions=[])
    worker = InProcessSchedulerWorker(settings, callback_client=callback, solver=lambda snapshot, *, time_limit_seconds: optimal_candidate(snapshot.input_hash))
    submission = build_submission(1, preview_id="preview-callback", snapshot_id="snapshot-callback")
    worker.process_submission(submission)
    if len(callback.submissions) != 1:
        raise AssertionError(f"expected one callback submission, got {len(callback.submissions)}")
    recorded = callback.submissions[0]
    return {
        "callback_preview_id": recorded["preview_id"],
        "callback_preview_version": recorded["preview_version"],
        "normalized_result_hash": recorded["normalized_result_hash"],
    }


def main() -> None:
    expect_production_config_validation()
    summary = {
        "production_config_validation": "passed",
        "queue_size_guardrail": verify_queue_size_protection_and_deterministic_fallback(),
        "solver_time_limit_forwarding": verify_solver_time_limit_is_forwarded(),
        "fallback_reasons": verify_timeout_and_execution_error_fallbacks(),
        "callback_submission": verify_async_submission_uses_callback(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
