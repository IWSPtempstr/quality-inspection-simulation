from __future__ import annotations

from dataclasses import dataclass

from ai_service.clients.redis_memory import InMemoryRedisClient
from ai_service.entities.memory import (
    SessionMemoryKey,
    SessionMemoryState,
    SessionSummary,
    SessionTurn,
)


@dataclass(frozen=True)
class RedisSessionMemoryRepository:
    client: InMemoryRedisClient
    recent_turns_ttl_seconds: int
    summary_ttl_seconds: int

    def load(self, key: SessionMemoryKey) -> SessionMemoryState:
        summary_payload = self.client.get_json(key.summary_key())
        turns_payload = self.client.get_json(key.turns_key()) or []
        summary = SessionSummary.model_validate(summary_payload) if summary_payload else None
        turns = tuple(SessionTurn.model_validate(item) for item in turns_payload)
        return SessionMemoryState(summary=summary, recent_turns=turns)

    def save_recent_turns(
        self,
        *,
        key: SessionMemoryKey,
        turns: tuple[SessionTurn, ...],
    ) -> None:
        self.client.set_json(
            key.turns_key(),
            [turn.model_dump(mode="json") for turn in turns],
            ttl_seconds=self.recent_turns_ttl_seconds,
        )

    def save_summary(
        self,
        *,
        key: SessionMemoryKey,
        summary: SessionSummary,
    ) -> None:
        self.client.set_json(
            key.summary_key(),
            summary.model_dump(mode="json"),
            ttl_seconds=self.summary_ttl_seconds,
        )
