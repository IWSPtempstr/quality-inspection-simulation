from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_service.clients import (
    BM25Record,
    ChromaRecord,
    InMemoryBM25Client,
    InMemoryChromaClient,
)
from ai_service.clients.reranker import HeuristicCrossEncoderReranker
from ai_service.core.context import RequestContext
from ai_service.entities.models import ExceptionCaseCandidateRequest
from ai_service.entities.retrieval import RetrievalActivation
from ai_service.repositories import (
    InMemoryActivationRepository,
    InMemoryExceptionCaseRepository,
    VersionedRetrievalRepository,
)
from ai_service.services import (
    AIEvaluationGate,
    CaseCandidateExtractionService,
    ExceptionCaseIndexingService,
    ExceptionCaseService,
    KnowledgeService,
    RetrievalService,
)


def _context() -> RequestContext:
    return RequestContext(
        correlation_id="corr-1",
        request_id="req-1",
        path="/internal/v1/exception-case-candidates",
        method="POST",
    )


def _candidate_request() -> ExceptionCaseCandidateRequest:
    return ExceptionCaseCandidateRequest(
        center_id="center-1",
        actor_id="actor-1",
        correlation_id="corr-1",
        event_id="evt-1",
        closed_event_snapshot={
            "event_type": "resource",
            "summary": "Compressor outage during thermal inspection.",
            "trigger": "compressor outage",
            "impact": "order delay risk",
            "disposition": "reroute to spare unit",
            "outcome": "schedule recovered",
            "equipment_ids": ["eq-1"],
            "project_codes": ["proj-a"],
            "tags": ["thermal", "compressor"],
            "evidence": [
                {
                    "standard_title": "Inspection Standard",
                    "version": "20260717",
                    "clause": "4.2",
                    "page": 11,
                    "content": "thermal inspection requires compressor isolation",
                }
            ],
        },
    )


def _retrieval_service(
    *,
    chroma_collections: dict[str, list[ChromaRecord]] | None = None,
    bm25_indexes: dict[str, list[BM25Record]] | None = None,
) -> RetrievalService:
    return RetrievalService(
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
            chroma_client=InMemoryChromaClient(chroma_collections),
            bm25_client=InMemoryBM25Client(bm25_indexes),
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


def test_candidate_extraction_is_non_persistent_and_structured() -> None:
    service = CaseCandidateExtractionService()

    result = service.extract(payload=_candidate_request(), context=_context())

    assert result.degraded is False
    assert result.trigger == "compressor outage"
    assert result.tags[:2] == ["resource", "thermal"]
    assert result.evidence[0].standard_title == "Inspection Standard"


def test_approved_case_is_indexed_only_after_review_and_outbox_publish() -> None:
    repository = InMemoryExceptionCaseRepository()
    case_service = ExceptionCaseService(repository=repository)
    chroma = InMemoryChromaClient()
    bm25 = InMemoryBM25Client()
    indexer = ExceptionCaseIndexingService(
        repository=repository,
        chroma_client=chroma,
        bm25_client=bm25,
    )

    candidate = case_service.create_review_candidate(
        payload=_candidate_request(),
        retention_until=datetime.now(tz=UTC) + timedelta(days=30),
    )
    assert repository.list_pending_outbox() == []

    case_service.approve_case(case_id=candidate.case_id, reviewer_id="reviewer-1")
    assert len(repository.list_pending_outbox()) == 1

    published = indexer.publish_pending()

    assert published == 1
    assert "resolved_exception_cases_current" in chroma._collections
    assert "resolved_exception_cases_bm25_current" in bm25._indexes
    assert repository.list_pending_outbox() == []


def test_revoked_case_is_removed_from_indexes() -> None:
    repository = InMemoryExceptionCaseRepository()
    case_service = ExceptionCaseService(repository=repository)
    chroma = InMemoryChromaClient()
    bm25 = InMemoryBM25Client()
    indexer = ExceptionCaseIndexingService(
        repository=repository,
        chroma_client=chroma,
        bm25_client=bm25,
    )

    candidate = case_service.create_review_candidate(
        payload=_candidate_request(),
        retention_until=datetime.now(tz=UTC) + timedelta(days=30),
    )
    case_service.approve_case(case_id=candidate.case_id, reviewer_id="reviewer-1")
    indexer.publish_pending()

    case_service.revoke_case(case_id=candidate.case_id)
    indexer.publish_pending()

    assert chroma._collections["resolved_exception_cases_current"] == []
    assert bm25._indexes["resolved_exception_cases_bm25_current"] == []


def test_evaluation_gate_checks_approval_and_center_isolation() -> None:
    future = datetime.now(tz=UTC) + timedelta(days=30)
    retrieval_service = _retrieval_service(
        chroma_collections={
            "resolved_exception_cases_current": [
                ChromaRecord(
                    document_id="case-1:1",
                    content="compressor outage rerouted to spare unit",
                    metadata={
                        "case_id": "case-1",
                        "center_id": "center-1",
                        "event_type": "resource",
                        "equipment_id": "eq-1",
                        "project_code": "proj-a",
                        "review_state": "approved",
                        "retention_until": future,
                        "access_scope": ["center:center-1"],
                    },
                )
            ]
        },
        bm25_indexes={
            "standard_chunks_bm25_current": [
                BM25Record(
                    document_id="std-1",
                    content="thermal inspection requires compressor isolation",
                    metadata={
                        "standard_title": "Inspection Standard",
                        "standard_version": "20260717",
                        "clause": "4.2",
                        "page": 11,
                        "access_scope": ["global"],
                    },
                )
            ]
        },
    )
    knowledge_service = KnowledgeService(
        retrieval_service=retrieval_service,
        reranker=HeuristicCrossEncoderReranker(),
    )
    gate = AIEvaluationGate(
        retrieval_service=retrieval_service,
        knowledge_service=knowledge_service,
    )

    result = gate.evaluate_resolved_case_retrieval(
        center_id="center-1",
        query_text="compressor outage",
        equipment_id="eq-1",
        project_code="proj-a",
        event_type="resource",
    )

    assert result.passed is True
    assert [check.name for check in result.checks] == [
        "approved_only",
        "center_isolation",
        "outage_degrades",
    ]
