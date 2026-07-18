from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ai_service.core.context import RequestContext
from ai_service.entities.models import DiagnosisRequest, KnowledgeQuery
from ai_service.entities.retrieval import RetrievalMetadataFilter, RetrievalQuery
from ai_service.services.knowledge import KnowledgeService
from ai_service.services.retrieval import RetrievalService


@dataclass(frozen=True)
class EvaluationCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvaluationGateResult:
    checks: tuple[EvaluationCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


@dataclass(frozen=True)
class AIEvaluationGate:
    retrieval_service: RetrievalService
    knowledge_service: KnowledgeService

    def evaluate_resolved_case_retrieval(
        self,
        *,
        center_id: str,
        query_text: str,
        equipment_id: str,
        project_code: str,
        event_type: str,
    ) -> EvaluationGateResult:
        result = self.retrieval_service.search(
            RetrievalQuery(
                corpus="resolved_cases",
                text=query_text,
                filters=RetrievalMetadataFilter(
                    center_id=center_id,
                    access_scopes=(f"center:{center_id}",),
                    equipment_ids=(equipment_id,),
                    project_codes=(project_code,),
                    event_types=(event_type,),
                    review_state="approved",
                    retention_not_before=datetime.now(tz=UTC),
                ),
            )
        )
        unauthorized = [hit for hit in result.hits if hit.metadata.get("center_id") != center_id]
        unapproved = [
            hit for hit in result.hits if hit.metadata.get("review_state") != "approved"
        ]
        return EvaluationGateResult(
            checks=(
                EvaluationCheck(
                    name="approved_only",
                    passed=not unapproved,
                    detail="retrieval excludes unapproved cases",
                ),
                EvaluationCheck(
                    name="center_isolation",
                    passed=not unauthorized,
                    detail="retrieval remains center-scoped",
                ),
                EvaluationCheck(
                    name="outage_degrades",
                    passed=bool(result.hits) or result.degraded,
                    detail="outages degrade safely instead of fabricating evidence",
                ),
            )
        )

    def evaluate_citation_requirement(
        self,
        *,
        payload: DiagnosisRequest,
        context: RequestContext,
    ) -> EvaluationGateResult:
        result = self.knowledge_service.answer(
            payload=KnowledgeQuery(
                center_id=payload.center_id,
                actor_id=payload.actor_id,
                query=(
                    payload.event_snapshot.summary
                    if payload.event_snapshot
                    else payload.event_id
                ),
            ),
            context=context,
        )
        return EvaluationGateResult(
            checks=(
                EvaluationCheck(
                    name="citations_when_evidence_available",
                    passed=(not result.evidence_available) or bool(result.citations),
                    detail="evidence-backed answers keep citations attached",
                ),
            )
        )
