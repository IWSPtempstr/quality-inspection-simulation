from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ai_service.clients.bm25 import BM25Record, InMemoryBM25Client
from ai_service.clients.chroma import ChromaRecord, InMemoryChromaClient
from ai_service.core.context import RequestContext
from ai_service.entities.cases import ExceptionCaseRecord
from ai_service.entities.models import (
    Citation,
    ExceptionCaseCandidateRequest,
    ExceptionCaseCandidateResult,
)
from ai_service.repositories.cases import InMemoryExceptionCaseRepository


@dataclass(frozen=True)
class ExceptionCaseService:
    repository: InMemoryExceptionCaseRepository

    def create_review_candidate(
        self,
        *,
        payload: ExceptionCaseCandidateRequest,
        retention_until: datetime,
    ) -> ExceptionCaseRecord:
        snapshot = payload.closed_event_snapshot
        case = ExceptionCaseRecord(
            case_id=f"case-{payload.event_id}",
            center_id=payload.center_id,
            event_id=payload.event_id,
            event_type=str(snapshot.get("event_type", "unknown")),
            summary=str(snapshot.get("summary", "No summary provided.")),
            trigger=str(snapshot.get("trigger", "undetermined")),
            impact=str(snapshot.get("impact", "undetermined")),
            disposition=str(snapshot.get("disposition", "undetermined")),
            outcome=str(snapshot.get("outcome", "undetermined")),
            tags=tuple(str(tag) for tag in snapshot.get("tags", [])),
            evidence=tuple(_citations_from_snapshot(snapshot)),
            equipment_ids=tuple(str(item) for item in snapshot.get("equipment_ids", [])),
            project_codes=tuple(str(item) for item in snapshot.get("project_codes", [])),
            retention_until=retention_until,
        )
        return self.repository.save_case(case)

    def approve_case(
        self,
        *,
        case_id: str,
        reviewer_id: str,
        reviewed_at: datetime | None = None,
    ) -> ExceptionCaseRecord:
        existing = self.repository.get_case(case_id)
        updated = existing.model_copy(
            update={
                "review_state": "approved",
                "reviewed_by": reviewer_id,
                "reviewed_at": reviewed_at or datetime.now(tz=UTC),
            }
        )
        self.repository.save_case(updated)
        self.repository.enqueue_outbox(case_id=case_id, action="index_upsert")
        return updated

    def revoke_case(self, *, case_id: str) -> ExceptionCaseRecord:
        existing = self.repository.get_case(case_id)
        updated = existing.model_copy(update={"review_state": "revoked"})
        self.repository.save_case(updated)
        self.repository.enqueue_outbox(case_id=case_id, action="index_delete")
        return updated


@dataclass(frozen=True)
class ExceptionCaseIndexingService:
    repository: InMemoryExceptionCaseRepository
    chroma_client: InMemoryChromaClient
    bm25_client: InMemoryBM25Client
    chroma_collection_name: str = "resolved_exception_cases_current"
    bm25_index_name: str = "resolved_exception_cases_bm25_current"

    def publish_pending(self) -> int:
        published = 0
        for outbox in self.repository.list_pending_outbox():
            if outbox.action == "index_upsert":
                self._upsert_case(outbox.case_id)
            else:
                self._delete_case(outbox.case_id)
            self.repository.mark_outbox_published(outbox_id=outbox.outbox_id)
            published += 1
        return published

    def _upsert_case(self, case_id: str) -> None:
        payloads = self.repository.build_index_payload(case_id)
        self.chroma_client.replace_records(
            collection_name=self.chroma_collection_name,
            document_id_prefix=f"{case_id}:",
            records=[
                ChromaRecord(
                    document_id=_document_id(case_id, index),
                    content=payload.content,
                    metadata=payload.model_dump(mode="json"),
                )
                for index, payload in enumerate(payloads, start=1)
            ],
        )
        self.bm25_client.replace_records(
            index_name=self.bm25_index_name,
            document_id_prefix=f"{case_id}:",
            records=[
                BM25Record(
                    document_id=_document_id(case_id, index),
                    content=payload.content,
                    metadata=payload.model_dump(mode="json"),
                )
                for index, payload in enumerate(payloads, start=1)
            ],
        )

    def _delete_case(self, case_id: str) -> None:
        self.chroma_client.delete_records(
            collection_name=self.chroma_collection_name,
            document_id_prefix=f"{case_id}:",
        )
        self.bm25_client.delete_records(
            index_name=self.bm25_index_name,
            document_id_prefix=f"{case_id}:",
        )


@dataclass(frozen=True)
class CaseCandidateExtractionService:
    retention_days: int = 30

    def extract(
        self,
        *,
        payload: ExceptionCaseCandidateRequest,
        context: RequestContext,
    ) -> ExceptionCaseCandidateResult:
        _ = context
        snapshot = payload.closed_event_snapshot
        summary = str(snapshot.get("summary", "Closed event summary unavailable."))
        trigger = str(snapshot.get("trigger", snapshot.get("event_type", "undetermined")))
        impact = str(snapshot.get("impact", "Operational impact pending review."))
        disposition = str(snapshot.get("disposition", "Needs reviewer confirmation."))
        outcome = str(snapshot.get("outcome", "Outcome pending reviewer confirmation."))
        tags = _normalize_tags(snapshot.get("tags", []), snapshot.get("event_type"))
        evidence = _citations_from_snapshot(snapshot)
        retention_until = datetime.now(tz=UTC).replace(microsecond=0) + timedelta(
            days=self.retention_days
        )
        return ExceptionCaseCandidateResult(
            summary=summary,
            trigger=trigger,
            impact=impact,
            disposition=disposition,
            outcome=outcome,
            tags=tags,
            evidence=evidence,
            retention_until=retention_until,
            degraded=False,
        )


def _citations_from_snapshot(snapshot: dict[str, object]) -> list[Citation]:
    evidence = snapshot.get("evidence", [])
    if not isinstance(evidence, list):
        return []
    citations: list[Citation] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        try:
            citations.append(Citation.model_validate(item))
        except Exception:
            continue
    return citations


def _normalize_tags(tags: object, event_type: object) -> list[str]:
    values: list[str] = []
    if isinstance(event_type, str) and event_type:
        values.append(event_type)
    if isinstance(tags, list):
        values.extend(str(tag) for tag in tags if str(tag).strip())
    deduplicated: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            deduplicated.append(value)
            seen.add(value)
    return deduplicated[:6]


def _document_id(case_id: str, index: int) -> str:
    return f"{case_id}:{index}"
