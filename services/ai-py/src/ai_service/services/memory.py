from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ai_service.entities.memory import (
    SessionMemoryKey,
    SessionMemoryState,
    SessionSummary,
    SessionTurn,
)
from ai_service.entities.models import DiagnosisMemoryStatus, DiagnosisRequest, DiagnosisResult
from ai_service.repositories.memory import RedisSessionMemoryRepository

SUMMARY_KEEP_TURNS = 4
MIN_RETAINED_TURNS = 2


@dataclass(frozen=True)
class SessionMemoryService:
    repository: RedisSessionMemoryRepository
    max_recent_turns: int
    max_recent_tokens: int

    def remember_diagnosis(
        self,
        *,
        payload: DiagnosisRequest,
        result: DiagnosisResult,
        recorded_at: datetime | None = None,
    ) -> SessionMemoryState | None:
        key = _session_key(payload)
        if key is None:
            return None
        now = recorded_at or datetime.now(tz=UTC)
        state = self.repository.load(key)
        appended = state.recent_turns + (
            _user_turn(payload=payload, recorded_at=now),
            _assistant_turn(result=result, recorded_at=now),
        )
        next_summary = state.summary
        next_turns = appended
        if _needs_compression(
            turns=appended,
            max_recent_turns=self.max_recent_turns,
            max_recent_tokens=self.max_recent_tokens,
        ):
            compressed_turns, next_turns = _split_turns_for_summary(
                turns=appended,
                max_recent_turns=self.max_recent_turns,
                max_recent_tokens=self.max_recent_tokens,
            )
            if compressed_turns:
                next_summary = _compress_summary(
                    prior_summary=state.summary,
                    turns=compressed_turns,
                    compressed_at=now,
                )
                self.repository.save_summary(key=key, summary=next_summary)
        self.repository.save_recent_turns(key=key, turns=next_turns)
        return SessionMemoryState(summary=next_summary, recent_turns=next_turns)

    def get_state(self, *, payload: DiagnosisRequest) -> SessionMemoryState | None:
        key = _session_key(payload)
        if key is None:
            return None
        return self.repository.load(key)

    def build_status(
        self,
        *,
        payload: DiagnosisRequest,
        state: SessionMemoryState | None,
    ) -> DiagnosisMemoryStatus:
        summary = state.summary if state is not None else None
        recent_turns = state.recent_turns if state is not None else ()
        return DiagnosisMemoryStatus(
            enabled=payload.session_id is not None,
            session_scoped=payload.session_id is not None,
            recent_turn_count=len(recent_turns),
            summary_available=summary is not None,
            compressed_turn_count=summary.compressed_turn_count if summary is not None else 0,
        )


def _session_key(payload: DiagnosisRequest) -> SessionMemoryKey | None:
    if not payload.session_id:
        return None
    return SessionMemoryKey(
        center_id=payload.center_id,
        actor_id=payload.actor_id,
        event_id=payload.event_id,
        session_id=payload.session_id,
    )


def _needs_compression(
    *,
    turns: tuple[SessionTurn, ...],
    max_recent_turns: int,
    max_recent_tokens: int,
) -> bool:
    if len(turns) > max_recent_turns:
        return True
    return sum(turn.token_count for turn in turns) > max_recent_tokens


def _compress_summary(
    *,
    prior_summary: SessionSummary | None,
    turns: tuple[SessionTurn, ...],
    compressed_at: datetime,
) -> SessionSummary:
    user_points = list(prior_summary.user_points if prior_summary else ())
    assistant_points = list(prior_summary.assistant_points if prior_summary else ())
    for turn in turns:
        snippet = _snippet(turn.content)
        if turn.role == "user" and snippet not in user_points:
            user_points.append(snippet)
        if turn.role == "assistant" and snippet not in assistant_points:
            assistant_points.append(snippet)
    return SessionSummary(
        compressed_at=compressed_at,
        compressed_turn_count=(prior_summary.compressed_turn_count if prior_summary else 0)
        + len(turns),
        compressed_token_count=(prior_summary.compressed_token_count if prior_summary else 0)
        + sum(turn.token_count for turn in turns),
        user_points=tuple(user_points[-8:]),
        assistant_points=tuple(assistant_points[-8:]),
    )


def _split_turns_for_summary(
    *,
    turns: tuple[SessionTurn, ...],
    max_recent_turns: int,
    max_recent_tokens: int,
) -> tuple[tuple[SessionTurn, ...], tuple[SessionTurn, ...]]:
    retained = list(turns[-SUMMARY_KEEP_TURNS:])
    compressed = list(turns[:-SUMMARY_KEEP_TURNS])
    while len(retained) > MIN_RETAINED_TURNS and (
        len(retained) > max_recent_turns or _turn_tokens(retained) > max_recent_tokens
    ):
        compressed.append(retained.pop(0))
    return tuple(compressed), tuple(retained)


def _user_turn(*, payload: DiagnosisRequest, recorded_at: datetime) -> SessionTurn:
    parts = [
        f"event:{payload.event_id}",
        payload.event_snapshot.summary if payload.event_snapshot else "event snapshot missing",
    ]
    if payload.event_snapshot and payload.event_snapshot.project_codes:
        parts.append(f"projects:{', '.join(payload.event_snapshot.project_codes)}")
    content = " | ".join(parts)
    return SessionTurn(
        role="user",
        content=content,
        token_count=_token_count(content),
        recorded_at=recorded_at,
    )


def _assistant_turn(*, result: DiagnosisResult, recorded_at: datetime) -> SessionTurn:
    parts = [
        f"confidence:{result.confidence}",
        f"recommendations:{'; '.join(result.recommendations) or 'none'}",
        f"gaps:{'; '.join(result.evidence_gaps) or 'none'}",
    ]
    content = " | ".join(parts)
    return SessionTurn(
        role="assistant",
        content=content,
        token_count=_token_count(content),
        recorded_at=recorded_at,
    )


def _token_count(text: str) -> int:
    return max(1, len(text.split()))


def _turn_tokens(turns: list[SessionTurn]) -> int:
    return sum(turn.token_count for turn in turns)


def _snippet(text: str, *, limit: int = 160) -> str:
    trimmed = " ".join(text.split())
    if len(trimmed) <= limit:
        return trimmed
    return f"{trimmed[: limit - 1]}…"
