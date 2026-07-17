from __future__ import annotations

from ai_service.agent import TOOL_LIMIT, ExceptionDiagnosisAgent
from ai_service.clients import (
    BM25Record,
    ChromaRecord,
    HeuristicCrossEncoderReranker,
    InMemoryBM25Client,
    InMemoryChromaClient,
)
from ai_service.core.context import RequestContext
from ai_service.entities.models import (
    DiagnosisEventSnapshot,
    DiagnosisOrderSnapshot,
    DiagnosisRequest,
    DiagnosisResourceSnapshot,
    DiagnosisScheduleSnapshot,
    DiagnosisSLARisk,
)
from ai_service.entities.retrieval import RetrievalActivation
from ai_service.repositories import (
    InMemoryActivationRepository,
    VersionedRetrievalRepository,
)
from ai_service.services import KnowledgeService, RetrievalService


def _context() -> RequestContext:
    return RequestContext(
        correlation_id="corr-1",
        request_id="req-1",
        path="/internal/v1/diagnoses",
        method="POST",
    )


def _agent(
    *,
    chroma_collections: dict[str, list[ChromaRecord]] | None = None,
    bm25_indexes: dict[str, list[BM25Record]] | None = None,
    reranker_available: bool = True,
) -> tuple[ExceptionDiagnosisAgent, InMemoryChromaClient, InMemoryBM25Client]:
    chroma = InMemoryChromaClient(chroma_collections)
    bm25 = InMemoryBM25Client(bm25_indexes)
    retrieval_service = RetrievalService(
        activation_repository=InMemoryActivationRepository(
            {
                "standards": RetrievalActivation(corpus="standards", active_version="20260717"),
                "resolved_cases": RetrievalActivation(
                    corpus="resolved_cases",
                    active_version="20260717",
                ),
            }
        ),
        repository=VersionedRetrievalRepository(
            chroma_client=chroma,
            bm25_client=bm25,
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
    knowledge_service = KnowledgeService(
        retrieval_service=retrieval_service,
        reranker=HeuristicCrossEncoderReranker(available=reranker_available),
    )
    return ExceptionDiagnosisAgent(knowledge_service), chroma, bm25


def _request() -> DiagnosisRequest:
    return DiagnosisRequest(
        center_id="center-1",
        actor_id="actor-1",
        event_id="evt-1",
        schedule_version=2,
        resource_snapshot_version=3,
        session_id="sess-1",
        event_snapshot=DiagnosisEventSnapshot(
            event_type="resource",
            summary="compressor outage during thermal inspection",
            affected_order_ids=("order-1",),
            affected_resource_ids=("eq-1",),
            equipment_ids=("eq-1",),
            project_codes=("proj-a",),
            related_step_ids=("step-1",),
        ),
        order_snapshots=(
            DiagnosisOrderSnapshot(
                order_id="order-1",
                title="Compressor thermal inspection",
                priority="urgent",
                status="scheduled",
                project_codes=("proj-a",),
            ),
        ),
        resource_snapshots=(
            DiagnosisResourceSnapshot(
                resource_id="eq-1",
                resource_type="equipment",
                display_name="Compressor A",
                status="down",
            ),
        ),
        schedule_snapshot=DiagnosisScheduleSnapshot(
            frozen_step_ids=("step-1",),
            sla_risks=(
                DiagnosisSLARisk(
                    order_id="order-1",
                    risk="late_start",
                    late_by_minutes=45,
                ),
            ),
        ),
    )


def test_diagnosis_returns_grounded_result_within_tool_budget() -> None:
    agent, _chroma, _bm25 = _agent(
        chroma_collections={
            "standard_chunks_20260717": [
                ChromaRecord(
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
            ],
            "resolved_exception_cases_20260717": [
                ChromaRecord(
                    document_id="case-1",
                    content="compressor outage resolved by rerouting to spare unit",
                    metadata={
                        "center_id": "center-1",
                        "access_scope": ["center:center-1"],
                        "equipment_id": "eq-1",
                        "project_code": "proj-a",
                        "event_type": "resource",
                        "review_state": "approved",
                    },
                )
            ],
        },
        bm25_indexes={
            "standard_chunks_bm25_20260717": [
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
            ],
            "resolved_exception_cases_bm25_20260717": [
                BM25Record(
                    document_id="case-1",
                    content="compressor outage resolved by rerouting to spare unit",
                    metadata={
                        "center_id": "center-1",
                        "access_scope": ["center:center-1"],
                        "equipment_id": "eq-1",
                        "project_code": "proj-a",
                        "event_type": "resource",
                        "review_state": "approved",
                    },
                )
            ],
        },
    )

    result = agent.diagnose(payload=_request(), context=_context())

    assert result.confidence == "high"
    assert result.degraded is False
    assert [citation.standard_title for citation in result.evidence] == ["Inspection Standard"]
    assert result.resolved_case_ids == ["case-1"]
    assert result.frozen_step_ids == ["step-1"]
    assert len(result.tool_calls) <= TOOL_LIMIT
    assert result.tool_calls == [
        "get_event_snapshot",
        "get_order_snapshot",
        "get_schedule_snapshot",
        "search_standards",
        "search_resolved_cases",
    ]


def test_diagnosis_degrades_when_retrieval_backends_are_unavailable() -> None:
    agent, chroma, bm25 = _agent()
    chroma.set_failure("standard_chunks_20260717")
    chroma.set_failure("resolved_exception_cases_20260717")
    bm25.set_failure("standard_chunks_bm25_20260717")
    bm25.set_failure("resolved_exception_cases_bm25_20260717")

    result = agent.diagnose(payload=_request(), context=_context())

    assert result.degraded is True
    assert result.confidence == "insufficient"
    assert result.evidence == []
    assert result.resolved_case_ids == []
    assert len(result.tool_calls) <= TOOL_LIMIT
    assert "No cited standards were retrieved for this event." in result.evidence_gaps


def test_diagnosis_is_evidence_insufficient_without_event_snapshot() -> None:
    agent, _chroma, _bm25 = _agent()

    result = agent.diagnose(
        payload=DiagnosisRequest(
            center_id="center-1",
            actor_id="actor-1",
            event_id="evt-missing",
            schedule_version=2,
            resource_snapshot_version=3,
        ),
        context=_context(),
    )

    assert result.degraded is True
    assert result.confidence == "insufficient"
    assert result.tool_calls == ["get_event_snapshot"]
    assert result.evidence_gaps == ["Event snapshot was not provided."]
