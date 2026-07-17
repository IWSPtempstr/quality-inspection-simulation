from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Citation(StrictModel):
    standard_title: str
    version: str
    clause: str
    page: int = Field(ge=1)
    content: str


class KnowledgeQuery(StrictModel):
    center_id: str
    actor_id: str
    query: str = Field(min_length=1)


class KnowledgeAnswer(StrictModel):
    answer: str
    citations: list[Citation]
    evidence_available: bool

    @model_validator(mode="after")
    def validate_evidence(self) -> "KnowledgeAnswer":
        if self.evidence_available and not self.citations:
            raise ValueError("citations are required when evidence is available")
        if not self.evidence_available and self.citations:
            raise ValueError("citations require evidence_available=true")
        return self


class DiagnosisRequest(StrictModel):
    center_id: str
    actor_id: str
    event_id: str
    schedule_version: int
    resource_snapshot_version: int
    session_id: str | None = None
    event_snapshot: "DiagnosisEventSnapshot | None" = None
    order_snapshots: tuple["DiagnosisOrderSnapshot", ...] = ()
    resource_snapshots: tuple["DiagnosisResourceSnapshot", ...] = ()
    schedule_snapshot: "DiagnosisScheduleSnapshot | None" = None


class DiagnosisEventSnapshot(StrictModel):
    event_type: str
    summary: str
    affected_order_ids: tuple[str, ...] = ()
    affected_resource_ids: tuple[str, ...] = ()
    equipment_ids: tuple[str, ...] = ()
    project_codes: tuple[str, ...] = ()
    related_step_ids: tuple[str, ...] = ()


class DiagnosisOrderSnapshot(StrictModel):
    order_id: str
    title: str
    priority: str | None = None
    status: str | None = None
    project_codes: tuple[str, ...] = ()


class DiagnosisResourceSnapshot(StrictModel):
    resource_id: str
    resource_type: Literal["equipment", "employee"]
    display_name: str | None = None
    status: str | None = None


class DiagnosisSLARisk(StrictModel):
    order_id: str
    risk: str
    late_by_minutes: int | None = None


class DiagnosisScheduleStep(StrictModel):
    step_id: str
    order_id: str
    frozen: bool = False
    status: str | None = None
    equipment_id: str | None = None
    employee_id: str | None = None


class DiagnosisScheduleSnapshot(StrictModel):
    frozen_step_ids: tuple[str, ...] = ()
    sla_risks: tuple[DiagnosisSLARisk, ...] = ()
    steps: tuple[DiagnosisScheduleStep, ...] = ()


class DiagnosisResult(StrictModel):
    event_id: str
    affected_orders: list[dict[str, Any]]
    frozen_step_ids: list[str]
    sla_risks: list[dict[str, Any]]
    affected_resources: list[dict[str, Any]]
    evidence: list[Citation]
    resolved_case_ids: list[str]
    recommendations: list[str]
    evidence_gaps: list[str]
    confidence: Literal["high", "medium", "low", "insufficient"]
    degraded: bool
    tool_calls: list[
        Literal[
            "get_event_snapshot",
            "get_order_snapshot",
            "get_resource_snapshot",
            "get_schedule_snapshot",
            "search_standards",
            "search_resolved_cases",
        ]
    ] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_evidence_confidence(self) -> "DiagnosisResult":
        if not self.evidence and self.confidence != "insufficient":
            raise ValueError("confidence must be insufficient when no evidence is present")
        return self


class AssistanceContext(StrictModel):
    center_id: str
    actor_id: str
    correlation_id: str
    context_version: str | None = None
    context_hash: str | None = None


class ScheduleExplanationRequest(AssistanceContext):
    preview_id: str
    subject_type: Literal["preview", "order", "step"]
    subject_id: str
    persisted_result: dict[str, Any]


class ScheduleExplanationResult(StrictModel):
    summary: str
    constraint_reasons: list[str]
    tradeoffs: list[str]
    frozen_step_ids: list[str]
    blockers: list[dict[str, Any]]
    evidence_available: bool
    degraded: bool


class DataQualityFinding(StrictModel):
    code: str
    message: str
    blocking: bool
    redacted_context: dict[str, Any] | None = None


class DataQualityExplanationRequest(AssistanceContext):
    scope: Literal["order", "resource", "schedule_preview"]
    findings: list[DataQualityFinding]


class DataQualityExplanation(StrictModel):
    code: str
    explanation: str
    suggested_correction: str | None = None


class DataQualityExplanationResult(StrictModel):
    explanations: list[DataQualityExplanation]
    degraded: bool


class ExceptionCaseCandidateRequest(AssistanceContext):
    event_id: str
    closed_event_snapshot: dict[str, Any]


class ExceptionCaseCandidateResult(StrictModel):
    summary: str
    trigger: str
    impact: str
    disposition: str
    outcome: str
    tags: list[str]
    evidence: list[Citation]
    retention_until: datetime
    degraded: bool


class AuditFilterSuggestionRequest(AssistanceContext):
    query: str = Field(min_length=1, max_length=1000)
    allowed_fields: list[Literal["actor_id", "action", "entity_id", "created_at"]]


class AuditFilter(StrictModel):
    field: Literal["actor_id", "action", "entity_id", "created_at"]
    operator: Literal["equals", "contains", "gte", "lte"]
    value: str


class AuditFilterSuggestionResult(StrictModel):
    filters: list[AuditFilter]
    explanation: str
    uncertainty: bool
    degraded: bool


class NotificationBodyDraftRequest(AssistanceContext):
    notification_id: str
    title: str
    source_body: str
    instruction: str | None = Field(default=None, max_length=1000)


class NotificationBodyDraftResult(StrictModel):
    body: str
    degraded: bool
