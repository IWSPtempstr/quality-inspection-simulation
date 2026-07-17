from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass
class _StoredValue:
    value: Any
    expires_at: datetime


@dataclass
class InMemoryRedisClient:
    now: Callable[[], datetime] = field(default=lambda: datetime.now(tz=UTC))
    _values: dict[str, _StoredValue] = field(default_factory=dict)

    def get_json(self, key: str) -> Any | None:
        record = self._values.get(key)
        if record is None:
            return None
        if record.expires_at <= self.now():
            self._values.pop(key, None)
            return None
        return record.value

    def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        self._values[key] = _StoredValue(
            value=value,
            expires_at=self.now() + timedelta(seconds=ttl_seconds),
        )

    def ttl_seconds(self, key: str) -> int | None:
        record = self._values.get(key)
        if record is None:
            return None
        if record.expires_at <= self.now():
            self._values.pop(key, None)
            return None
        return int((record.expires_at - self.now()).total_seconds())
