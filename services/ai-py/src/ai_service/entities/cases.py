from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator

from ai_service.entities.models import Citation, StrictModel

ReviewState = Literal["submitted", "approved", "revoked"]
OutboxAction = Literal["index_upsert", "index_delete"]


class ExceptionCaseRecord(StrictModel):
    case_id: str
    center_id: str
    event_id: str
    event_type: str
    summary: str
    trigger: str
    impact: str
    disposition: str
    outcome: str
    tags: tuple[str, ...] = ()
    evidence: tuple[Citation, ...] = ()
    equipment_ids: tuple[str, ...] = ()
    project_codes: tuple[str, ...] = ()
    review_state: ReviewState = "submitted"
    retention_until: datetime
    access_scope: tuple[str, ...] = ()
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    @field_validator("retention_until", "reviewed_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)

    @field_validator("access_scope")
    @classmethod
    def default_scope(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        if value:
            return value
        center_id = info.data.get("center_id")
        if not isinstance(center_id, str) or not center_id:
            return value
        return (f"center:{center_id}",)

    @property
    def is_active(self) -> bool:
        return self.review_state == "approved" and self.retention_until >= datetime.now(tz=UTC)


class ExceptionCaseOutboxRecord(StrictModel):
    outbox_id: str
    case_id: str
    action: OutboxAction
    created_at: datetime
    published_at: datetime | None = None

    @field_validator("created_at", "published_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)


class ExceptionCaseIndexPayload(StrictModel):
    case_id: str
    content: str
    center_id: str
    event_type: str
    equipment_id: str | None = None
    project_code: str | None = None
    review_state: str = "approved"
    retention_until: datetime
    access_scope: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("retention_until")
    @classmethod
    def normalize_retention_until(cls, value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)
