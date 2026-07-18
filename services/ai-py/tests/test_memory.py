from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_service.clients.redis_memory import InMemoryRedisClient
from ai_service.conf.settings import Settings
from ai_service.core.context import RequestContext
from ai_service.entities.models import (
    DiagnosisEventSnapshot,
    DiagnosisMemoryStatus,
    DiagnosisRequest,
    DiagnosisResult,
)
from ai_service.repositories.memory import RedisSessionMemoryRepository
from ai_service.services.assistance import AssistanceService
from ai_service.services.memory import SessionMemoryService


class Clock:
    def __init__(self, now: datetime):
        self.value = now

    def now(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def _request(
    *,
    center_id: str = "center-1",
    actor_id: str = "actor-1",
    event_id: str = "event-1",
    session_id: str = "session-1",
    summary: str = "compressor outage during thermal inspection",
) -> DiagnosisRequest:
    return DiagnosisRequest(
        center_id=center_id,
        actor_id=actor_id,
        event_id=event_id,
        session_id=session_id,
        schedule_version=2,
        resource_snapshot_version=3,
        event_snapshot=DiagnosisEventSnapshot(
            event_type="resource",
            summary=summary,
            affected_order_ids=("order-1",),
            project_codes=("proj-a",),
        ),
    )


def _result(*, recommendation: str = "Inspect clause 4.2 first.") -> DiagnosisResult:
    return DiagnosisResult(
        event_id="event-1",
        affected_orders=[{"order_id": "order-1"}],
        frozen_step_ids=[],
        sla_risks=[],
        affected_resources=[],
        evidence=[],
        resolved_case_ids=[],
        recommendations=[recommendation],
        evidence_gaps=["Event snapshot needs more detail."],
        confidence="insufficient",
        memory_status=DiagnosisMemoryStatus(
            enabled=False,
            session_scoped=False,
            recent_turn_count=0,
            summary_available=False,
            compressed_turn_count=0,
        ),
        degraded=True,
        tool_calls=["get_event_snapshot"],
    )


def _context() -> RequestContext:
    return RequestContext(
        correlation_id="corr-1",
        request_id="req-1",
        path="/internal/v1/diagnoses",
        method="POST",
    )


def _service(clock: Clock, *, max_turns: int = 8, max_tokens: int = 6000) -> SessionMemoryService:
    return SessionMemoryService(
        repository=RedisSessionMemoryRepository(
            client=InMemoryRedisClient(now=clock.now),
            recent_turns_ttl_seconds=24 * 60 * 60,
            summary_ttl_seconds=7 * 24 * 60 * 60,
        ),
        max_recent_turns=max_turns,
        max_recent_tokens=max_tokens,
    )


def test_memory_is_scoped_by_center_user_event_and_session() -> None:
    clock = Clock(datetime(2026, 7, 17, tzinfo=UTC))
    service = _service(clock)

    state_a = service.remember_diagnosis(
        payload=_request(),
        result=_result(),
        recorded_at=clock.now(),
    )
    state_b = service.remember_diagnosis(
        payload=_request(session_id="session-2"),
        result=_result(recommendation="Use spare compressor."),
        recorded_at=clock.now(),
    )

    assert state_a is not None
    assert state_b is not None
    assert len(state_a.recent_turns) == 2
    assert len(state_b.recent_turns) == 2
    assert state_a.recent_turns[1].content != state_b.recent_turns[1].content


def test_recent_turns_keep_24_hour_ttl() -> None:
    clock = Clock(datetime(2026, 7, 17, tzinfo=UTC))
    service = _service(clock)
    payload = _request()

    service.remember_diagnosis(payload=payload, result=_result(), recorded_at=clock.now())
    state = service.get_state(payload=payload)

    assert state is not None
    assert len(state.recent_turns) == 2

    clock.advance(timedelta(hours=24, seconds=1))

    expired = service.get_state(payload=payload)
    assert expired is not None
    assert expired.recent_turns == ()
    assert expired.summary is None


def test_compresses_older_turns_after_eight_turns_and_keeps_summary_for_seven_days() -> None:
    clock = Clock(datetime(2026, 7, 17, tzinfo=UTC))
    service = _service(clock)
    payload = _request()

    for index in range(5):
        service.remember_diagnosis(
            payload=_request(summary=f"event detail {index}"),
            result=_result(recommendation=f"recommendation {index}"),
            recorded_at=clock.now(),
        )
        clock.advance(timedelta(minutes=1))

    state = service.get_state(payload=payload)

    assert state is not None
    assert state.summary is not None
    assert len(state.recent_turns) == 4
    assert state.summary.compressed_turn_count == 6
    assert "event:event-1 | event detail 0 | projects:proj-a" in state.summary.user_points

    clock.advance(timedelta(days=7, seconds=1))

    expired = service.get_state(payload=payload)
    assert expired is not None
    assert expired.summary is None


def test_compresses_when_recent_token_budget_is_exceeded() -> None:
    clock = Clock(datetime(2026, 7, 17, tzinfo=UTC))
    service = _service(clock, max_tokens=20)
    payload = _request(summary="alpha beta gamma delta epsilon zeta eta theta iota kappa lambda")

    service.remember_diagnosis(payload=payload, result=_result(), recorded_at=clock.now())
    service.remember_diagnosis(payload=payload, result=_result(), recorded_at=clock.now())
    service.remember_diagnosis(payload=payload, result=_result(), recorded_at=clock.now())

    state = service.get_state(payload=payload)
    assert state is not None
    assert state.summary is not None
    assert state.summary.compressed_token_count > 20
    assert len(state.recent_turns) == 2


def test_assistance_service_records_diagnosis_memory_when_session_exists() -> None:
    clock = Clock(datetime(2026, 7, 17, tzinfo=UTC))
    memory_service = _service(clock)
    service = AssistanceService(
        Settings(service_bearer_token="test-token"),
        memory_service=memory_service,
    )
    payload = _request()

    service.diagnose_exception(payload=payload, context=_context())
    state = memory_service.get_state(payload=payload)

    assert state is not None
    assert len(state.recent_turns) == 2
    result = service.diagnose_exception(payload=payload, context=_context()).value
    assert result.memory_status.model_dump() == {
        "enabled": True,
        "session_scoped": True,
        "recent_turn_count": 4,
        "summary_available": False,
        "compressed_turn_count": 0,
    }


def test_assistance_service_skips_memory_without_session_id() -> None:
    clock = Clock(datetime(2026, 7, 17, tzinfo=UTC))
    memory_service = _service(clock)
    service = AssistanceService(
        Settings(service_bearer_token="test-token"),
        memory_service=memory_service,
    )
    payload = _request(session_id=None)  # type: ignore[arg-type]

    service.diagnose_exception(payload=payload, context=_context())

    assert memory_service.get_state(payload=payload) is None
    result = service.diagnose_exception(payload=payload, context=_context()).value
    assert result.memory_status.model_dump() == {
        "enabled": False,
        "session_scoped": False,
        "recent_turn_count": 0,
        "summary_available": False,
        "compressed_turn_count": 0,
    }
