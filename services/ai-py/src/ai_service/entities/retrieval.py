from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from ai_service.entities.models import StrictModel

RetrievalCorpus = Literal["standards", "resolved_cases"]
RetrievalBackend = Literal["chroma", "bm25", "hybrid", "none"]


class RetrievalMetadataFilter(StrictModel):
    center_id: str | None = None
    access_scopes: tuple[str, ...] = ()
    standard_version: str | None = None
    standard_ids: tuple[str, ...] = ()
    equipment_ids: tuple[str, ...] = ()
    project_codes: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    review_state: str | None = None
    retention_not_before: datetime | None = None

    @field_validator("retention_not_before")
    @classmethod
    def normalize_retention_boundary(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)

    def matches(self, metadata: dict[str, Any]) -> bool:
        if self.center_id is not None and metadata.get("center_id") != self.center_id:
            return False

        if self.access_scopes:
            doc_scopes = metadata.get("access_scope", ())
            if isinstance(doc_scopes, str):
                doc_scope_values = {doc_scopes}
            else:
                doc_scope_values = {str(value) for value in doc_scopes}
            required_scopes = set(self.access_scopes)
            if not doc_scope_values.intersection(required_scopes):
                return False

        if (
            self.standard_version is not None
            and metadata.get("standard_version") != self.standard_version
        ):
            return False

        if self.standard_ids and metadata.get("standard_id") not in self.standard_ids:
            return False

        if self.equipment_ids and metadata.get("equipment_id") not in self.equipment_ids:
            return False

        if self.project_codes and metadata.get("project_code") not in self.project_codes:
            return False

        if self.event_types and metadata.get("event_type") not in self.event_types:
            return False

        if self.review_state is not None and metadata.get("review_state") != self.review_state:
            return False

        if self.retention_not_before is not None:
            retention_until = metadata.get("retention_until")
            if not isinstance(retention_until, datetime):
                return False
            if retention_until.tzinfo is None:
                retention_until = retention_until.replace(tzinfo=UTC)
            if retention_until < self.retention_not_before:
                return False

        return True


class RetrievalQuery(StrictModel):
    corpus: RetrievalCorpus
    text: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)
    filters: RetrievalMetadataFilter = Field(default_factory=RetrievalMetadataFilter)
    allow_version_fallback: bool = True
    correlation_id: str | None = None


class RetrievalHit(StrictModel):
    document_id: str
    content: str
    metadata: dict[str, Any]
    score: float
    backend: RetrievalBackend
    version: str


class RetrievalActivation(StrictModel):
    corpus: RetrievalCorpus
    active_version: str
    fallback_versions: tuple[str, ...] = ()


class RetrievalResult(StrictModel):
    corpus: RetrievalCorpus
    hits: list[RetrievalHit]
    degraded: bool
    degradation_reasons: list[str]
    backend_used: RetrievalBackend
    version_used: str | None = None

    @property
    def evidence_available(self) -> bool:
        return bool(self.hits)


class HybridRetrievalResult(StrictModel):
    corpus: RetrievalCorpus
    hits: list[RetrievalHit]
    degraded: bool
    degradation_reasons: list[str]
    version_used: str | None = None
    vector_backend_available: bool = False
    lexical_backend_available: bool = False

    @property
    def evidence_available(self) -> bool:
        return bool(self.hits)
