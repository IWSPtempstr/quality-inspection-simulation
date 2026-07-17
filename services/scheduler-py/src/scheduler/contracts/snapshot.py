"""Immutable scheduling snapshot input contract."""

from datetime import UTC, datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    StrictStr,
    field_validator,
)


class SchedulingSnapshot(BaseModel):
    """Opaque center-scoped input captured by Go before any scheduling work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: StrictStr
    input_hash: StrictStr
    as_of: datetime
    base_schedule_version: StrictInt = Field(ge=0)
    resource_snapshot_version: StrictInt = Field(ge=0)
    orders: tuple[dict[str, JsonValue], ...]
    resources: dict[str, JsonValue]
    frozen_steps: tuple[dict[str, JsonValue], ...]

    @field_validator("as_of")
    @classmethod
    def normalize_as_of_to_utc(cls, value: datetime) -> datetime:
        """Reject naive instants so canonical output has one unambiguous representation."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        return value.astimezone(UTC)


def parse_scheduling_snapshot(payload: object) -> SchedulingSnapshot:
    """Parse untrusted transport data into the immutable snapshot contract."""
    return SchedulingSnapshot.model_validate(payload)
