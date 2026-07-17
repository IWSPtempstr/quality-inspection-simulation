"""Normalized result entity used at the S1/S4 boundary."""

from pydantic import BaseModel, ConfigDict

from scheduler.contracts.candidate import ScheduleCandidate


class NormalizedCandidate(BaseModel):
    """A candidate and the deterministic hash S4 must bind in its callback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: ScheduleCandidate
    normalized_result_hash: str

