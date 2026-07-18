from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ai_service.entities.cases import (
    ExceptionCaseIndexPayload,
    ExceptionCaseOutboxRecord,
    ExceptionCaseRecord,
    OutboxAction,
)


@dataclass
class InMemoryExceptionCaseRepository:
    _cases: dict[str, ExceptionCaseRecord] = field(default_factory=dict)
    _outbox: dict[str, ExceptionCaseOutboxRecord] = field(default_factory=dict)
    _sequence: int = 0

    def save_case(self, case: ExceptionCaseRecord) -> ExceptionCaseRecord:
        self._cases[case.case_id] = case
        return case

    def get_case(self, case_id: str) -> ExceptionCaseRecord:
        return self._cases[case_id]

    def list_cases(self) -> list[ExceptionCaseRecord]:
        return [self._cases[key] for key in sorted(self._cases)]

    def enqueue_outbox(
        self,
        *,
        case_id: str,
        action: OutboxAction,
        created_at: datetime | None = None,
    ) -> ExceptionCaseOutboxRecord:
        self._sequence += 1
        record = ExceptionCaseOutboxRecord(
            outbox_id=f"outbox-{self._sequence}",
            case_id=case_id,
            action=action,
            created_at=created_at or datetime.now(tz=UTC),
        )
        self._outbox[record.outbox_id] = record
        return record

    def list_pending_outbox(self) -> list[ExceptionCaseOutboxRecord]:
        return [
            self._outbox[key]
            for key in sorted(self._outbox)
            if self._outbox[key].published_at is None
        ]

    def mark_outbox_published(
        self,
        *,
        outbox_id: str,
        published_at: datetime | None = None,
    ) -> ExceptionCaseOutboxRecord:
        existing = self._outbox[outbox_id]
        updated = existing.model_copy(update={"published_at": published_at or datetime.now(tz=UTC)})
        self._outbox[outbox_id] = updated
        return updated

    def build_index_payload(self, case_id: str) -> list[ExceptionCaseIndexPayload]:
        case = self.get_case(case_id)
        if case.review_state != "approved":
            return []

        equipment_ids = case.equipment_ids or (None,)
        project_codes = case.project_codes or (None,)
        payloads: list[ExceptionCaseIndexPayload] = []
        for equipment_id in equipment_ids:
            for project_code in project_codes:
                payloads.append(
                    ExceptionCaseIndexPayload(
                        case_id=case.case_id,
                        content=_index_content(case),
                        center_id=case.center_id,
                        event_type=case.event_type,
                        equipment_id=equipment_id,
                        project_code=project_code,
                        review_state=case.review_state,
                        retention_until=case.retention_until,
                        access_scope=case.access_scope,
                    )
                )
        return payloads


def _index_content(case: ExceptionCaseRecord) -> str:
    parts = [case.summary, case.trigger, case.impact, case.disposition, case.outcome]
    if case.tags:
        parts.append(" ".join(case.tags))
    return " | ".join(part.strip() for part in parts if part.strip())
