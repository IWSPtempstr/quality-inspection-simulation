import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
    ):
        self._gateway = DisabledLLMGateway()
        self._prompts = PromptLoader(settings)
        self._knowledge = knowledge_service or _default_knowledge_service()
        self._diagnosis_agent = diagnosis_agent or ExceptionDiagnosisAgent(self._knowledge)
        self._memory = memory_service or _default_memory_service(settings)

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
        self._memory.remember_diagnosis(payload=payload, result=result)
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
        return ScheduleExplanationResult(
            summary="Schedule explanation is not available in A1.",
            constraint_reasons=[],
            tradeoffs=[],
            frozen_step_ids=[],
            blockers=[],
            evidence_available=False,
            degraded=True,
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
        return DataQualityExplanationResult(
            explanations=[
                DataQualityExplanation(
                    code=finding.code,
                    explanation="Structured explanation is not available in A1.",
                )
                for finding in payload.findings
            ],
            degraded=True,
        )

    def extract_exception_case_candidate(
        self,
        *,
        payload: ExceptionCaseCandidateRequest,
        context: RequestContext,
    ) -> ExceptionCaseCandidateResult:
        log_payload(logger, "exception_case_candidate_request", payload.model_dump())
        _ = context
        self._prompts.load("assistance/exception_case_candidate")
        return ExceptionCaseCandidateResult(
            summary="Case candidate extraction is not available in A1.",
            trigger="unavailable",
            impact="unavailable",
            disposition="unavailable",
            outcome="unavailable",
            tags=[],
            evidence=[],
            retention_until=datetime.now(tz=UTC) + timedelta(days=30),
            degraded=True,
        )

    def suggest_audit_filters(
        self,
        *,
        payload: AuditFilterSuggestionRequest,
        context: RequestContext,
    ) -> AuditFilterSuggestionResult:
        log_payload(logger, "audit_filter_suggestion_request", payload.model_dump())
        _ = context
        self._prompts.load("assistance/audit_filters")
        return AuditFilterSuggestionResult(
            filters=[],
            explanation="Audit filter suggestions are not available in A1.",
            uncertainty=True,
            degraded=True,
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
        return NotificationBodyDraftResult(
            body="Notification drafting is not available in A1.",
            degraded=True,
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
