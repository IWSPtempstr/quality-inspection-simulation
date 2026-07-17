"""In-process S4 scheduler worker with no persistence or queue dependency."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Thread
from typing import Any

from scheduler.api.schemas import ScheduleSubmission
from scheduler.conf.settings import SchedulerSettings
from scheduler.contracts.candidate import ScheduleCandidate
from scheduler.core.canonical_json import normalized_candidate
from scheduler.cp_sat import solve_snapshot
from scheduler.sla_fallback import FallbackRejectedError, build_fallback_candidate
from scheduler.worker.callback import SchedulerCallbackClient


@dataclass(frozen=True)
class SchedulerJobFailure:
    """Sanitized job-level failure kept only for observability and tests."""

    preview_id: str
    preview_version: int
    reason: str
    attempts: int


class InProcessSchedulerWorker:
    """Accepts immutable submissions and posts candidates back to Go."""

    def __init__(
        self,
        settings: SchedulerSettings,
        *,
        callback_client: SchedulerCallbackClient | None = None,
        solver: Callable[..., ScheduleCandidate] = solve_snapshot,
        fallback_builder: Callable[..., ScheduleCandidate] = build_fallback_candidate,
    ) -> None:
        self._settings = settings
        self._callback_client = callback_client or SchedulerCallbackClient(
            base_url=str(settings.callback_base_url or "http://localhost"),
            token=settings.callback_service_token.get_secret_value()
            if settings.callback_service_token is not None
            else "",
        )
        self._solver = solver
        self._fallback_builder = fallback_builder
        self.failures: list[SchedulerJobFailure] = []

    def submit(self, submission: ScheduleSubmission) -> None:
        """Dispatch the immutable job asynchronously within this process only."""
        thread = Thread(target=self.process_submission, args=(submission,), daemon=True)
        thread.start()

    def process_submission(self, submission: ScheduleSubmission) -> None:
        """Compute one candidate and try the bounded callback contract."""
        try:
            candidate = self._candidate_for(submission)
            normalized = normalized_candidate(candidate)
            self._callback_client.submit_candidate(
                preview_id=submission.preview_id,
                preview_version=submission.preview_version,
                snapshot_id=submission.snapshot.snapshot_id,
                input_hash=submission.snapshot.input_hash,
                normalized_result_hash=normalized.normalized_result_hash,
                candidate=normalized.candidate,
            )
        except ValueError as exc:
            self.failures.append(
                SchedulerJobFailure(
                    preview_id=submission.preview_id,
                    preview_version=submission.preview_version,
                    reason=str(exc),
                    attempts=1,
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.failures.append(
                SchedulerJobFailure(
                    preview_id=submission.preview_id,
                    preview_version=submission.preview_version,
                    reason=exc.__class__.__name__
                    if isinstance(exc, FallbackRejectedError)
                    else str(exc),
                    attempts=3,
                )
            )

    def _candidate_for(self, submission: ScheduleSubmission) -> ScheduleCandidate:
        snapshot = submission.snapshot
        if self._work_count(snapshot) > self._settings.queue_size_protection_limit:
            return self._fallback_builder(
                snapshot,
                trigger="input_size_protection_threshold_exceeded",
                cp_sat_status="unknown",
                input_size_limit=self._settings.queue_size_protection_limit,
            )
        try:
            candidate = self._solver(
                snapshot,
                time_limit_seconds=self._settings.solver_time_limit_seconds,
            )
        except Exception:  # noqa: BLE001
            return self._fallback_builder(
                snapshot,
                trigger="cp_sat_execution_error",
                cp_sat_status="execution_error",
            )
        if candidate.solver_status in {"optimal", "feasible"}:
            return candidate
        if candidate.solver_status == "infeasible":
            return self._fallback_builder(
                snapshot,
                trigger="cp_sat_infeasible",
                cp_sat_status="infeasible",
            )
        return self._fallback_builder(
            snapshot,
            trigger="cp_sat_timeout_without_feasible_solution",
            cp_sat_status="unknown",
        )

    @staticmethod
    def _work_count(snapshot: Any) -> int:
        return sum(
            len(order.get("steps", []))
            for order in snapshot.model_dump(mode="python")["orders"]
        )
