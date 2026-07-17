"""Transport schemas for the authenticated S4 ingress."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from scheduler.contracts.snapshot import SchedulingSnapshot


class ScheduleSubmission(BaseModel):
    """Authenticated envelope tying one immutable snapshot to one preview version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preview_id: StrictStr
    preview_version: StrictInt = Field(ge=1)
    snapshot: SchedulingSnapshot


class ScheduleAccepted(BaseModel):
    """Transport-only acceptance payload; work continues asynchronously."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preview_id: StrictStr
    preview_version: StrictInt = Field(ge=1)
    snapshot_id: StrictStr
    status: StrictStr = "accepted"
