import logging
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import Request

from ai_service.agent import ExceptionDiagnosisAgent
from ai_service.clients.bm25 import InMemoryBM25Client
from ai_service.clients.chroma import InMemoryChromaClient
from ai_service.clients.llm_gateway import DisabledLLMGateway, GatewayPrompt
from ai_service.clients.redis_memory import InMemoryRedisClient
from ai_service.clients.reranker import HeuristicCrossEncoderReranker
from ai_service.conf.settings import Settings
from ai_service.core.context import RequestContext
from ai_service.core.logging import log_payload
from ai_service.entities.models import (
    AuditFilter,
    AuditFilterSuggestionRequest,
    AuditFilterSuggestionResult,
    DataQualityExplanation,
    DataQualityExplanationRequest,
    DataQualityExplanationResult,
    DiagnosisRequest,
    DiagnosisResult,
    ExceptionCaseCandidateRequest,
    ExceptionCaseCandidateResult,
    KnowledgeAnswer,
    KnowledgeQuery,
    NotificationBodyDraftRequest,
    NotificationBodyDraftResult,
    ScheduleExplanationRequest,
    ScheduleExplanationResult,
)
from ai_service.entities.retrieval import RetrievalActivation
from ai_service.prompt.loader import PromptLoader
from ai_service.repositories.memory import RedisSessionMemoryRepository
from ai_service.repositories.retrieval import (
    InMemoryActivationRepository,
    VersionedRetrievalRepository,
)
from ai_service.services.cases import CaseCandidateExtractionService
from ai_service.services.knowledge import KnowledgeService
from ai_service.services.memory import SessionMemoryService
from ai_service.services.retrieval import RetrievalService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlaceholderResult[T]:
    value: T
    is_placeholder: bool = False


class AssistanceService:
    def __init__(
        self,
        settings: Settings,
        knowledge_service: KnowledgeService | None = None,
        diagnosis_agent: ExceptionDiagnosisAgent | None = None,
        memory_service: SessionMemoryService | None = None,
        case_candidate_service: CaseCandidateExtractionService | None = None,
    ):
        self._gateway = DisabledLLMGateway()
        self._prompts = PromptLoader(settings)
        self._knowledge = knowledge_service or _default_knowledge_service()
        self._diagnosis_agent = diagnosis_agent or ExceptionDiagnosisAgent(self._knowledge)
        self._memory = memory_service or _default_memory_service(settings)
        self._case_candidates = case_candidate_service or CaseCandidateExtractionService()

    def query_knowledge(
        self,
        *,
        payload: KnowledgeQuery,
        context: RequestContext,
    ) -> KnowledgeAnswer:
        log_payload(logger, "knowledge_query", payload.model_dump())
        self._gateway.render_unavailable(
            GatewayPrompt("knowledge/query", self._prompts.load("knowledge/query"))
        )
        return self._knowledge.answer(payload=payload, context=context)

    def diagnose_exception(
        self,
        *,
        payload: DiagnosisRequest,
        context: RequestContext,
    ) -> PlaceholderResult[DiagnosisResult]:
        log_payload(logger, "diagnosis_request", payload.model_dump())
        self._prompts.load("diagnosis/system")
        result = self._diagnosis_agent.diagnose(payload=payload, context=context)
        memory_state = self._memory.remember_diagnosis(payload=payload, result=result)
        result = result.model_copy(
            update={"memory_status": self._memory.build_status(payload=payload, state=memory_state)}
        )
        return PlaceholderResult(
            value=result,
            is_placeholder=result.degraded,
        )

    def explain_schedule(
        self,
        *,
        payload: ScheduleExplanationRequest,
        context: RequestContext,
    ) -> ScheduleExplanationResult:
        log_payload(logger, "schedule_explanation_request", payload.model_dump())
        _ = context
        self._prompts.load("assistance/schedule_explanation")
        persisted = payload.persisted_result
        changes = persisted.get("changes", [])
        blockers = persisted.get("blockers", [])
        frozen_step_ids = list(_as_strings(persisted.get("frozen_step_ids", [])))
        constraint_reasons = _as_strings(
            [
                persisted.get("solver_status"),
                persisted.get("fallback_reason"),
                *(_as_strings(persisted.get("constraint_reasons", []))),
            ]
        )
        tradeoffs = _as_strings(
            [
                f"algorithm={persisted.get('algorithm_used')}"
                if persisted.get("algorithm_used")
                else None,
                f"changed_steps={len(changes)}" if isinstance(changes, list) else None,
                f"weighted_delay={persisted.get('weighted_delay_minutes')}"
                if persisted.get("weighted_delay_minutes") is not None
                else None,
            ]
        )
        evidence_available = bool(constraint_reasons or blockers or frozen_step_ids or tradeoffs)
        summary = "Persisted schedule result reviewed."
        if persisted.get("algorithm_used"):
            summary = f"{persisted['algorithm_used']} result reviewed for {payload.subject_type}."
        return ScheduleExplanationResult(
            summary=summary,
            constraint_reasons=constraint_reasons,
            tradeoffs=tradeoffs,
            frozen_step_ids=frozen_step_ids,
            blockers=blockers if isinstance(blockers, list) else [],
            evidence_available=evidence_available,
            degraded=not evidence_available,
        )

    def explain_data_quality(
        self,
        *,
        payload: DataQualityExplanationRequest,
        context: RequestContext,
    ) -> DataQualityExplanationResult:
        log_payload(logger, "data_quality_request", payload.model_dump())
        _ = context
        self._prompts.load("assistance/data_quality")
        explanations = [
            DataQualityExplanation(
                code=finding.code,
                explanation=_rule_explanation(finding.code, finding.message, finding.blocking),
                suggested_correction=_suggested_correction(finding.code, finding.redacted_context),
            )
            for finding in payload.findings
        ]
        return DataQualityExplanationResult(
            explanations=explanations,
            degraded=False,
        )

    def extract_exception_case_candidate(
        self,
        *,
        payload: ExceptionCaseCandidateRequest,
        context: RequestContext,
    ) -> ExceptionCaseCandidateResult:
        log_payload(logger, "exception_case_candidate_request", payload.model_dump())
        self._prompts.load("assistance/exception_case_candidate")
        return self._case_candidates.extract(payload=payload, context=context)

    def suggest_audit_filters(
        self,
        *,
        payload: AuditFilterSuggestionRequest,
        context: RequestContext,
    ) -> AuditFilterSuggestionResult:
        log_payload(logger, "audit_filter_suggestion_request", payload.model_dump())
        _ = context
        self._prompts.load("assistance/audit_filters")
        filters = _suggest_filters(payload.query, payload.allowed_fields)
        return AuditFilterSuggestionResult(
            filters=filters,
            explanation="Structured audit filters were derived from the provided query.",
            uncertainty=not bool(filters),
            degraded=False,
        )

    def draft_notification_body(
        self,
        *,
        payload: NotificationBodyDraftRequest,
        context: RequestContext,
    ) -> NotificationBodyDraftResult:
        log_payload(logger, "notification_body_draft_request", payload.model_dump())
        _ = context
        self._prompts.load("assistance/notification_body")
        body = payload.source_body.strip()
        if payload.instruction:
            body = f"{payload.title}\n\n{body}\n\nEdit note: {payload.instruction.strip()}"
        elif not body.startswith(payload.title):
            body = f"{payload.title}\n\n{body}"
        return NotificationBodyDraftResult(
            body=body,
            degraded=False,
        )


def get_assistance_service(request: Request) -> AssistanceService:
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        settings = Settings()
        request.app.state.settings = settings
    return AssistanceService(settings)


def _default_knowledge_service() -> KnowledgeService:
    retrieval_service = RetrievalService(
        activation_repository=InMemoryActivationRepository(
            {
                "standards": RetrievalActivation(corpus="standards", active_version="current"),
                "resolved_cases": RetrievalActivation(
                    corpus="resolved_cases",
                    active_version="current",
                ),
            }
        ),
        repository=VersionedRetrievalRepository(
            chroma_client=InMemoryChromaClient(),
            bm25_client=InMemoryBM25Client(),
            chroma_prefixes={
                "standards": "standard_chunks",
                "resolved_cases": "resolved_exception_cases",
            },
            bm25_prefixes={
                "standards": "standard_chunks_bm25",
                "resolved_cases": "resolved_exception_cases_bm25",
            },
        ),
    )
    reranker = HeuristicCrossEncoderReranker()

    return KnowledgeService(
        retrieval_service=retrieval_service,
        reranker=reranker,
    )


def _default_memory_service(settings: Settings) -> SessionMemoryService:
    return SessionMemoryService(
        repository=RedisSessionMemoryRepository(
            client=InMemoryRedisClient(),
            recent_turns_ttl_seconds=settings.memory_recent_ttl_seconds,
            summary_ttl_seconds=settings.memory_summary_ttl_seconds,
        ),
        max_recent_turns=settings.memory_max_turns,
        max_recent_tokens=settings.memory_max_tokens,
    )


def _as_strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


def _rule_explanation(code: str, message: str, blocking: bool) -> str:
    prefix = "Blocking rule failed" if blocking else "Rule warning"
    return f"{prefix}: {code} — {message}"


def _suggested_correction(code: str, redacted_context: dict[str, object] | None) -> str | None:
    if code.endswith("missing"):
        return "Provide the missing required field and retry validation."
    if code.endswith("stale_version"):
        return "Refresh the latest source version before resubmitting."
    if redacted_context and "expected" in redacted_context:
        return f"Align the value with {redacted_context['expected']}."
    return None


def _suggest_filters(query: str, allowed_fields: Sequence[str]) -> list[AuditFilter]:
    lowered = query.lower()
    filters: list[AuditFilter] = []
    if "actor" in lowered and "actor_id" in allowed_fields:
        filters.append(
            AuditFilter(field="actor_id", operator="contains", value="actor")
        )
    if "create" in lowered and "action" in allowed_fields:
        filters.append(AuditFilter(field="action", operator="contains", value="create"))
    if "order" in lowered and "entity_id" in allowed_fields:
        filters.append(AuditFilter(field="entity_id", operator="contains", value="order"))
    if "after" in lowered and "created_at" in allowed_fields:
        filters.append(AuditFilter(field="created_at", operator="gte", value="after"))
    return filters
