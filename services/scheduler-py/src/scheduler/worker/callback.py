"""HTTP callback adapter with bounded retries and sanitized failures."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx

from scheduler.contracts.candidate import ScheduleCandidate


@dataclass(frozen=True)
class CallbackFailure:
    """Sanitized local failure record retained only inside the worker process."""

    preview_id: str
    preview_version: int
    attempts: int
    reason: str


class SchedulerCallbackClient:
    """Posts validated candidates back to the matching Go preview."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client or httpx.Client(timeout=5.0)
        self._sleep = sleep or (
            lambda seconds: None if seconds <= 0 else __import__("time").sleep(seconds)
        )

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
        body = {
            "snapshot_id": snapshot_id,
            "input_hash": input_hash,
            "version": preview_version,
            "normalized_result_hash": normalized_result_hash,
            "candidate": candidate.model_dump(mode="json"),
        }
        path = f"/internal/v1/schedule-previews/{preview_id}/candidate"
        last_reason = "callback failed"
        for attempt, delay in enumerate((0.0, 1.0, 5.0), start=1):
            if delay:
                self._sleep(delay)
            try:
                response = self._client.post(
                    f"{self._base_url}{path}",
                    headers={"X-Scheduler-Callback-Token": self._token},
                    json=body,
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_reason = exc.__class__.__name__
                if attempt == 3:
                    raise RuntimeError(last_reason) from exc
                continue
            if response.status_code >= 500:
                last_reason = f"http_{response.status_code}"
                if attempt == 3:
                    raise RuntimeError(last_reason)
                continue
            if response.status_code >= 400:
                raise ValueError(f"http_{response.status_code}")
            return
        raise RuntimeError(last_reason)

    def close(self) -> None:
        self._client.close()
