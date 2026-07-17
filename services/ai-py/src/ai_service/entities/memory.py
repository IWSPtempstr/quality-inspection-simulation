from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ai_service.entities.models import StrictModel


class SessionMemoryKey(StrictModel):
    center_id: str
    actor_id: str
    event_id: str
    session_id: str

    def turns_key(self) -> str:
        return (
            "memory:turns:"
            f"{self.center_id}:{self.actor_id}:{self.event_id}:{self.session_id}"
        )

    def summary_key(self) -> str:
        return (
            "memory:summary:"
            f"{self.center_id}:{self.actor_id}:{self.event_id}:{self.session_id}"
        )


class SessionTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    token_count: int = Field(ge=1)
    recorded_at: datetime


class SessionSummary(StrictModel):
    compressed_at: datetime
    compressed_turn_count: int = Field(ge=1)
    compressed_token_count: int = Field(ge=1)
    user_points: tuple[str, ...] = ()
    assistant_points: tuple[str, ...] = ()


class SessionMemoryState(StrictModel):
    summary: SessionSummary | None = None
    recent_turns: tuple[SessionTurn, ...] = ()
