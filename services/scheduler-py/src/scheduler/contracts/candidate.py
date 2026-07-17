"""Immutable candidate-result contract, without solver behavior."""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    StrictBool,
    StrictStr,
    model_validator,
)

FallbackReason = Literal[
    "cp_sat_infeasible",
    "cp_sat_timeout_without_feasible_solution",
    "cp_sat_execution_error",
    "input_size_protection_threshold_exceeded",
]


class ScheduleCandidate(BaseModel):
    """A validated, opaque result supplied by a later solver or fallback phase."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_hash: StrictStr
    algorithm_used: Literal["cp_sat", "sla_fallback"]
    solver_status: StrictStr
    fallback_used: StrictBool
    fallback_reason: FallbackReason | None
    blocked_steps: tuple[dict[str, JsonValue], ...]
    schedule: dict[str, JsonValue]
    metrics: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_fallback_shape(self) -> "ScheduleCandidate":
        """Only validate declared fallback metadata; algorithm selection belongs to S2/S3."""
        if self.fallback_used and self.fallback_reason is None:
            raise ValueError("fallback_reason is required when fallback_used is true")
        if not self.fallback_used and self.fallback_reason is not None:
            raise ValueError("fallback_reason must be null when fallback_used is false")
        return self


def parse_schedule_candidate(payload: object) -> ScheduleCandidate:
    """Parse a later solver's result without selecting or executing an algorithm."""
    return ScheduleCandidate.model_validate(payload)
