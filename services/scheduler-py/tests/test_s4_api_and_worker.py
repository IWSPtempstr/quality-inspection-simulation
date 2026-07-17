"""S4 ingress and callback retry coverage."""

from __future__ import annotations

import json

import httpx
import pytest

from scheduler.api.app import create_app
from scheduler.api.schemas import ScheduleSubmission
from scheduler.conf.settings import SchedulerSettings
from scheduler.contracts.candidate import ScheduleCandidate
from scheduler.contracts.snapshot import SchedulingSnapshot
from scheduler.core.canonical_json import normalized_candidate
from scheduler.worker.callback import SchedulerCallbackClient
from scheduler.worker.runner import InProcessSchedulerWorker


def _settings() -> SchedulerSettings:
    return SchedulerSettings(
        environment="test",
        service_bearer_token="ingress-token",
        callback_service_token="callback-token",
        callback_base_url="http://callback.internal",
    )


def _snapshot() -> SchedulingSnapshot:
    return SchedulingSnapshot.model_validate(
        {
            "snapshot_id": "snapshot-s4",
            "input_hash": "sha256:s4-input",
            "as_of": "2026-07-16T00:00:00Z",
            "base_schedule_version": 1,
            "resource_snapshot_version": 1,
            "orders": [
                {
                    "id": "order-1",
                    "priority": "normal",
                    "promise_at": "2026-07-16T06:00:00Z",
                    "steps": [
                        {
                            "id": "step-1",
                            "duration_minutes": 30,
                            "equipment_ids": ["eq-1"],
                            "employee_ids": ["employee-1"],
                            "required_skill": "inspect",
                        }
                    ],
                }
            ],
            "resources": {
                "equipment": [{"id": "eq-1"}],
                "employees": [{"id": "employee-1", "skills": ["inspect"]}],
            },
            "frozen_steps": [],
        }
    )


def _submission() -> ScheduleSubmission:
    return ScheduleSubmission(preview_id="preview-1", preview_version=3, snapshot=_snapshot())


def _candidate() -> ScheduleCandidate:
    return ScheduleCandidate.model_validate(
        {
            "input_hash": "sha256:input",
            "algorithm_used": "cp_sat",
            "solver_status": "optimal",
            "fallback_used": False,
            "fallback_reason": None,
            "blocked_steps": [],
            "schedule": {
                "steps": [
                    {
                        "id": "step-1",
                        "order_id": "order-1",
                        "project_id": "project-1",
                        "starts_at": "2026-07-16T00:00:00Z",
                        "ends_at": "2026-07-16T00:30:00Z",
                    }
                ]
            },
            "metrics": {"scheduled_step_count": 1},
        }
    )


@pytest.mark.anyio
async def test_ingress_rejects_missing_or_invalid_bearer() -> None:
    app = create_app(_settings(), worker=RecordingWorker(_settings()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/internal/v1/schedule",
            json=_submission().model_dump(mode="json"),
        )
        assert response.status_code == 401

        response = await client.post(
            "/internal/v1/schedule",
            headers={"Authorization": "Bearer wrong"},
            json=_submission().model_dump(mode="json"),
        )
        assert response.status_code == 401


@pytest.mark.anyio
async def test_ingress_validates_envelope_and_accepts_bound_preview() -> None:
    worker = RecordingWorker(_settings())
    app = create_app(_settings(), worker=worker)
    transport = httpx.ASGITransport(app=app)
    payload = _submission().model_dump(mode="json")
    payload["preview_version"] = 0

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        invalid = await client.post(
            "/internal/v1/schedule",
            headers={"Authorization": "Bearer ingress-token"},
            json=payload,
        )
        assert invalid.status_code == 422

        accepted = await client.post(
            "/internal/v1/schedule",
            headers={"Authorization": "Bearer ingress-token"},
            json=_submission().model_dump(mode="json"),
        )
        assert accepted.status_code == 202
        assert accepted.json() == {
            "preview_id": "preview-1",
            "preview_version": 3,
            "snapshot_id": "snapshot-s4",
            "status": "accepted",
        }
    assert worker.submissions == [_submission()]


def test_callback_client_sends_expected_auth_and_body() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"status": "ok"})

    client = SchedulerCallbackClient(
        base_url="http://callback.internal",
        token="callback-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    normalized = normalized_candidate(_candidate())
    client.submit_candidate(
        preview_id="preview-1",
        preview_version=5,
        snapshot_id="snapshot-1",
        input_hash="sha256:input",
        normalized_result_hash=normalized.normalized_result_hash,
        candidate=normalized.candidate,
    )

    assert len(observed) == 1
    request = observed[0]
    assert request.headers["X-Scheduler-Callback-Token"] == "callback-token"
    assert request.url.path == "/internal/v1/schedule-previews/preview-1/candidate"
    assert json.loads(request.content.decode("utf-8")) == {
        "snapshot_id": "snapshot-1",
        "input_hash": "sha256:input",
        "version": 5,
        "normalized_result_hash": normalized.normalized_result_hash,
        "candidate": normalized.candidate.model_dump(mode="json"),
    }


def test_callback_client_retries_transient_failures_then_stops() -> None:
    attempts: list[int] = []
    sleeps: list[float] = []

    def failing(request: httpx.Request) -> httpx.Response:
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "ok"})

    client = SchedulerCallbackClient(
        base_url="http://callback.internal",
        token="callback-token",
        client=httpx.Client(transport=httpx.MockTransport(failing)),
        sleep=sleeps.append,
    )
    normalized = normalized_candidate(_candidate())

    client.submit_candidate(
        preview_id="preview-1",
        preview_version=5,
        snapshot_id="snapshot-1",
        input_hash="sha256:input",
        normalized_result_hash=normalized.normalized_result_hash,
        candidate=normalized.candidate,
    )

    assert attempts == [1, 2, 3]
    assert sleeps == [1.0, 5.0]


def test_callback_client_stops_immediately_on_4xx() -> None:
    attempts: list[int] = []

    def rejected(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(409)

    client = SchedulerCallbackClient(
        base_url="http://callback.internal",
        token="callback-token",
        client=httpx.Client(transport=httpx.MockTransport(rejected)),
    )

    with pytest.raises(ValueError, match="http_409"):
        normalized = normalized_candidate(_candidate())
        client.submit_candidate(
            preview_id="preview-1",
            preview_version=5,
            snapshot_id="snapshot-1",
            input_hash="sha256:input",
            normalized_result_hash=normalized.normalized_result_hash,
            candidate=normalized.candidate,
        )

    assert len(attempts) == 1


def test_worker_records_sanitized_failure_after_three_transient_attempts() -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    callback = SchedulerCallbackClient(
        base_url="http://callback.internal",
        token="callback-token",
        client=httpx.Client(transport=httpx.MockTransport(unavailable)),
        sleep=lambda _: None,
    )
    worker = InProcessSchedulerWorker(_settings(), callback_client=callback)
    worker.process_submission(_submission())

    assert len(worker.failures) == 1
    failure = worker.failures[0]
    assert failure.preview_id == "preview-1"
    assert failure.preview_version == 3
    assert failure.reason == "http_503"
    assert failure.attempts == 3


def test_worker_stops_immediately_on_terminal_4xx_and_records_one_failure() -> None:
    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409)

    callback = SchedulerCallbackClient(
        base_url="http://callback.internal",
        token="callback-token",
        client=httpx.Client(transport=httpx.MockTransport(rejected)),
        sleep=lambda _: None,
    )
    worker = InProcessSchedulerWorker(_settings(), callback_client=callback)
    worker.process_submission(_submission())

    assert len(worker.failures) == 1
    failure = worker.failures[0]
    assert failure.reason == "http_409"
    assert failure.attempts == 1


def test_cross_language_candidate_hash_vector_is_stable() -> None:
    candidate = ScheduleCandidate.model_validate(
        {
            "input_hash": "sha256:vector",
            "algorithm_used": "cp_sat",
            "solver_status": "optimal",
            "fallback_used": False,
            "fallback_reason": None,
            "blocked_steps": [],
            "schedule": {
                "steps": [
                    {
                        "id": "step-1",
                        "order_id": "order-1",
                        "project_id": "project-1",
                        "starts_at": "2026-07-16T08:00:00+08:00",
                        "ends_at": "2026-07-16T08:30:00+08:00",
                    }
                ]
            },
            "metrics": {"scheduled_step_count": 1, "blocked_step_count": 0},
        }
    )

    assert (
        normalized_candidate(candidate).normalized_result_hash
        == "sha256:ffcea49f1eb07a54c58f3861f279e934060dfb5c0e819b31c9fd8e6118d6a19e"
    )


class RecordingWorker(InProcessSchedulerWorker):
    """Test helper that captures accepted submissions without spawning threads."""

    def __init__(self, settings: SchedulerSettings) -> None:
        super().__init__(settings)
        self.submissions: list[ScheduleSubmission] = []

    def submit(self, submission: ScheduleSubmission) -> None:
        self.submissions.append(submission)
