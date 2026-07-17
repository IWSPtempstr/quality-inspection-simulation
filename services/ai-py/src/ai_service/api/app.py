"""Internal FastAPI application for bounded AI assistance."""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from ai_service.conf.settings import Settings
from ai_service.core.context import RequestContext
from ai_service.core.logging import configure_logging
from ai_service.entities.models import (
    AuditFilterSuggestionRequest,
    AuditFilterSuggestionResult,
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
from ai_service.services.assistance import AssistanceService


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the A1 internal AI service with bearer-only authentication."""
    resolved = settings or Settings()
    configure_logging()
    app = FastAPI(
        title="AI Internal API",
        version="1.0.0",
        description="Authenticated internal AI assistance service.",
    )
    service = AssistanceService(resolved)

    def require_service_bearer(authorization: str | None) -> None:
        expected = resolved.service_bearer_token or ""
        token = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing_or_invalid_authorization",
            )
        if token != expected:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    def request_context(request: Request, request_id: str | None = None) -> RequestContext:
        return RequestContext.from_headers(
            path=request.url.path,
            method=request.method,
            correlation_id=request.headers.get("X-Correlation-ID"),
            request_id=request_id,
        )

    @app.post("/internal/v1/knowledge/query", response_model=KnowledgeAnswer)
    async def query_standards(
        payload: KnowledgeQuery,
        request: Request,
        authorization: str | None = Header(default=None),
        x_request_id: str | None = Header(default=None),
    ) -> KnowledgeAnswer:
        require_service_bearer(authorization)
        context = request_context(request, x_request_id)
        return service.query_knowledge(payload=payload, context=context)

    @app.post("/internal/v1/diagnoses", response_model=DiagnosisResult)
    async def diagnose_exception(
        payload: DiagnosisRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_request_id: str | None = Header(default=None),
    ) -> DiagnosisResult:
        require_service_bearer(authorization)
        result = service.diagnose_exception(
            payload=payload,
            context=request_context(request, x_request_id),
        )
        return result.value

    @app.post("/internal/v1/schedule-explanations", response_model=ScheduleExplanationResult)
    async def explain_schedule_result(
        payload: ScheduleExplanationRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_request_id: str | None = Header(default=None),
    ) -> ScheduleExplanationResult:
        require_service_bearer(authorization)
        context = request_context(request, x_request_id)
        return service.explain_schedule(payload=payload, context=context)

    @app.post(
        "/internal/v1/data-quality-explanations",
        response_model=DataQualityExplanationResult,
    )
    async def explain_failed_rules(
        payload: DataQualityExplanationRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_request_id: str | None = Header(default=None),
    ) -> DataQualityExplanationResult:
        require_service_bearer(authorization)
        return service.explain_data_quality(
            payload=payload,
            context=request_context(request, x_request_id),
        )

    @app.post(
        "/internal/v1/exception-case-candidates",
        response_model=ExceptionCaseCandidateResult,
    )
    async def extract_exception_case_candidate(
        payload: ExceptionCaseCandidateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_request_id: str | None = Header(default=None),
    ) -> ExceptionCaseCandidateResult:
        require_service_bearer(authorization)
        return service.extract_exception_case_candidate(
            payload=payload,
            context=request_context(request, x_request_id),
        )

    @app.post(
        "/internal/v1/audit-filter-suggestions",
        response_model=AuditFilterSuggestionResult,
    )
    async def suggest_audit_filters(
        payload: AuditFilterSuggestionRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_request_id: str | None = Header(default=None),
    ) -> AuditFilterSuggestionResult:
        require_service_bearer(authorization)
        return service.suggest_audit_filters(
            payload=payload,
            context=request_context(request, x_request_id),
        )

    @app.post(
        "/internal/v1/notification-body-drafts",
        response_model=NotificationBodyDraftResult,
    )
    async def draft_notification_body(
        payload: NotificationBodyDraftRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_request_id: str | None = Header(default=None),
    ) -> NotificationBodyDraftResult:
        require_service_bearer(authorization)
        return service.draft_notification_body(
            payload=payload,
            context=request_context(request, x_request_id),
        )

    @app.get("/healthz", include_in_schema=False)
    async def health() -> Response:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


app = create_app()
