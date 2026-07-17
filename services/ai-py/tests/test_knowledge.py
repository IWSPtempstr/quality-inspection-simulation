from __future__ import annotations

from ai_service.clients import (
    BM25Record,
    ChromaRecord,
    HeuristicCrossEncoderReranker,
    InMemoryBM25Client,
    InMemoryChromaClient,
)
from ai_service.core.context import RequestContext
from ai_service.entities.models import KnowledgeQuery
from ai_service.entities.retrieval import RetrievalActivation
from ai_service.repositories import InMemoryActivationRepository, VersionedRetrievalRepository
from ai_service.services import KnowledgeService, RetrievalService


def _knowledge_service(
    *,
    chroma_collections: dict[str, list[ChromaRecord]] | None = None,
    bm25_indexes: dict[str, list[BM25Record]] | None = None,
    reranker_available: bool = True,
) -> tuple[KnowledgeService, InMemoryChromaClient, InMemoryBM25Client]:
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
    service = KnowledgeService(
        retrieval_service=retrieval_service,
        reranker=HeuristicCrossEncoderReranker(available=reranker_available),
    )
    return service, chroma, bm25


def _context() -> RequestContext:
    return RequestContext(
        correlation_id="corr-1",
        request_id="req-1",
        path="/internal/v1/knowledge/query",
        method="POST",
    )


def test_answer_uses_hybrid_rrf_and_limits_citations_to_five() -> None:
    service, _chroma, _bm25 = _knowledge_service(
        chroma_collections={
            "standard_chunks_20260717": [
                ChromaRecord(
                    document_id="shared-1",
                    content="grounding inspection clause content",
                    metadata={
                        "standard_title": "Electrical Safety Standard",
                        "standard_version": "20260717",
                        "clause": "5.1",
                        "page": 12,
                    },
                ),
                ChromaRecord(
                    document_id="vector-only",
                    content="lockout verification steps",
                    metadata={
                        "standard_title": "Maintenance Standard",
                        "standard_version": "20260717",
                        "clause": "6.3",
                        "page": 21,
                    },
                ),
                *[
                    ChromaRecord(
                        document_id=f"extra-{index}",
                        content=f"grounding checklist item {index}",
                        metadata={
                            "standard_title": f"Checklist {index}",
                            "standard_version": "20260717",
                            "clause": f"8.{index}",
                            "page": index + 1,
                        },
                    )
                    for index in range(1, 6)
                ],
            ]
        },
        bm25_indexes={
            "standard_chunks_bm25_20260717": [
                BM25Record(
                    document_id="shared-1",
                    content="grounding inspection clause content",
                    metadata={
                        "standard_title": "Electrical Safety Standard",
                        "standard_version": "20260717",
                        "clause": "5.1",
                        "page": 12,
                    },
                ),
                BM25Record(
                    document_id="lexical-only",
                    content="grounding clause panel bonding",
                    metadata={
                        "standard_title": "Bonding Standard",
                        "standard_version": "20260717",
                        "clause": "2.4",
                        "page": 7,
                    },
                ),
            ]
        },
    )

    answer = service.answer(
        payload=KnowledgeQuery(
            center_id="center-1",
            actor_id="actor-1",
            query="grounding inspection clause",
        ),
        context=_context(),
    )

    assert answer.evidence_available is True
    assert len(answer.citations) == 5
    assert answer.citations[0].standard_title == "Electrical Safety Standard"
    assert "Top evidence:" in answer.answer


def test_answer_degrades_to_fused_order_when_reranker_is_unavailable() -> None:
    service, _chroma, _bm25 = _knowledge_service(
        chroma_collections={
            "standard_chunks_20260717": [
                ChromaRecord(
                    document_id="vector-hit",
                    content="calibration tolerance procedure",
                    metadata={
                        "standard_title": "Calibration Standard",
                        "standard_version": "20260717",
                        "clause": "3.2",
                        "page": 9,
                    },
                )
            ]
        },
        bm25_indexes={
            "standard_chunks_bm25_20260717": [
                BM25Record(
                    document_id="lexical-hit",
                    content="calibration tolerance checklist",
                    metadata={
                        "standard_title": "Tolerance Standard",
                        "standard_version": "20260717",
                        "clause": "4.5",
                        "page": 15,
                    },
                )
            ]
        },
        reranker_available=False,
    )

    answer = service.answer(
        payload=KnowledgeQuery(
            center_id="center-1",
            actor_id="actor-1",
            query="calibration tolerance",
        ),
        context=_context(),
    )

    assert answer.evidence_available is True
    assert "Degraded retrieval or reranking fallback was used." in answer.answer


def test_answer_returns_no_evidence_when_both_backends_are_unavailable() -> None:
    service, chroma, bm25 = _knowledge_service()
    chroma.set_failure("standard_chunks_20260717")
    bm25.set_failure("standard_chunks_bm25_20260717")

    answer = service.answer(
        payload=KnowledgeQuery(
            center_id="center-1",
            actor_id="actor-1",
            query="arc flash boundary",
        ),
        context=_context(),
    )

    assert answer.model_dump() == {
        "answer": "No cited standards are currently available for this query.",
        "citations": [],
        "evidence_available": False,
    }


def test_impact_analysis_uses_same_cited_set() -> None:
    service, _chroma, _bm25 = _knowledge_service(
        chroma_collections={
            "standard_chunks_20260717": [
                ChromaRecord(
                    document_id="impact-1",
                    content="thermal inspection interval for compressor bearings",
                    metadata={
                        "standard_title": "Thermal Standard",
                        "standard_version": "20260717",
                        "clause": "9.1",
                        "page": 30,
                    },
                )
            ]
        },
        bm25_indexes={
            "standard_chunks_bm25_20260717": [
                BM25Record(
                    document_id="impact-1",
                    content="thermal inspection interval for compressor bearings",
                    metadata={
                        "standard_title": "Thermal Standard",
                        "standard_version": "20260717",
                        "clause": "9.1",
                        "page": 30,
                    },
                )
            ]
        },
    )

    analysis = service.analyze_impact(
        payload=KnowledgeQuery(
            center_id="center-1",
            actor_id="actor-1",
            query="compressor thermal inspection",
        ),
        context=_context(),
    )

    assert analysis.evidence_available is True
    assert analysis.degraded is False
    assert analysis.findings[0].impact == "direct"
    assert analysis.findings[0].clause == "9.1"
