from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_service.clients import (
    BM25Record,
    ChromaRecord,
    InMemoryBM25Client,
    InMemoryChromaClient,
)
from ai_service.entities.retrieval import (
    RetrievalActivation,
    RetrievalMetadataFilter,
    RetrievalQuery,
)
from ai_service.repositories import InMemoryActivationRepository, VersionedRetrievalRepository
from ai_service.services import RetrievalService


def _service(
    *,
    chroma_collections: dict[str, list[ChromaRecord]] | None = None,
    bm25_indexes: dict[str, list[BM25Record]] | None = None,
    activations: dict[str, RetrievalActivation] | None = None,
) -> tuple[RetrievalService, InMemoryChromaClient, InMemoryBM25Client]:
    chroma = InMemoryChromaClient(chroma_collections)
    bm25 = InMemoryBM25Client(bm25_indexes)
    activation_repository = InMemoryActivationRepository(
        activations
        or {
            "standards": RetrievalActivation(corpus="standards", active_version="20260717"),
            "resolved_cases": RetrievalActivation(
                corpus="resolved_cases",
                active_version="20260717",
            ),
        }
    )
    repository = VersionedRetrievalRepository(
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
    )
    return (
        RetrievalService(
            activation_repository=activation_repository,
            repository=repository,
        ),
        chroma,
        bm25,
    )


def test_version_activation_falls_back_to_previous_validated_version() -> None:
    service, chroma, _bm25 = _service(
        chroma_collections={
            "standard_chunks_20260710": [
                ChromaRecord(
                    document_id="std-1",
                    content="electrical grounding procedure",
                    metadata={
                        "standard_version": "20260710",
                        "standard_id": "STD-1",
                        "access_scope": ["global"],
                    },
                )
            ]
        },
        activations={
            "standards": RetrievalActivation(
                corpus="standards",
                active_version="20260717",
                fallback_versions=("20260710",),
            ),
            "resolved_cases": RetrievalActivation(
                corpus="resolved_cases",
                active_version="20260717",
            ),
        },
    )
    chroma.set_failure("standard_chunks_20260717")

    result = service.search(
        RetrievalQuery(
            corpus="standards",
            text="grounding procedure",
            filters=RetrievalMetadataFilter(access_scopes=("global",)),
        )
    )

    assert result.degraded is True
    assert result.version_used == "20260710"
    assert result.backend_used == "chroma"
    assert [hit.document_id for hit in result.hits] == ["std-1"]


def test_metadata_filters_restrict_standard_version_and_scope() -> None:
    service, _chroma, _bm25 = _service(
        chroma_collections={
            "standard_chunks_20260717": [
                ChromaRecord(
                    document_id="std-active",
                    content="pressure calibration clause 5",
                    metadata={
                        "standard_version": "20260717",
                        "standard_id": "STD-A",
                        "access_scope": ["global"],
                    },
                ),
                ChromaRecord(
                    document_id="std-old",
                    content="pressure calibration retired clause",
                    metadata={
                        "standard_version": "20260701",
                        "standard_id": "STD-B",
                        "access_scope": ["global"],
                    },
                ),
            ]
        }
    )

    result = service.search(
        RetrievalQuery(
            corpus="standards",
            text="pressure calibration",
            filters=RetrievalMetadataFilter(
                access_scopes=("global",),
                standard_version="20260717",
            ),
        )
    )

    assert [hit.document_id for hit in result.hits] == ["std-active"]
    assert result.degraded is False


def test_center_and_access_scope_isolation_for_resolved_cases() -> None:
    future = datetime.now(tz=UTC) + timedelta(days=30)
    service, _chroma, _bm25 = _service(
        chroma_collections={
            "resolved_exception_cases_20260717": [
                ChromaRecord(
                    document_id="case-c1",
                    content="compressor outage resolved with spare unit",
                    metadata={
                        "center_id": "center-1",
                        "access_scope": ["center:center-1"],
                        "equipment_id": "eq-1",
                        "project_code": "proj-a",
                        "event_type": "resource",
                        "review_state": "approved",
                        "retention_until": future,
                    },
                ),
                ChromaRecord(
                    document_id="case-c2",
                    content="compressor outage in another center",
                    metadata={
                        "center_id": "center-2",
                        "access_scope": ["center:center-2"],
                        "equipment_id": "eq-1",
                        "project_code": "proj-a",
                        "event_type": "resource",
                        "review_state": "approved",
                        "retention_until": future,
                    },
                ),
            ]
        }
    )

    result = service.search(
        RetrievalQuery(
            corpus="resolved_cases",
            text="compressor outage",
            filters=RetrievalMetadataFilter(
                center_id="center-1",
                access_scopes=("center:center-1",),
                equipment_ids=("eq-1",),
                project_codes=("proj-a",),
                event_types=("resource",),
                review_state="approved",
                retention_not_before=datetime.now(tz=UTC),
            ),
        )
    )

    assert [hit.document_id for hit in result.hits] == ["case-c1"]
    assert all(hit.metadata["center_id"] == "center-1" for hit in result.hits)


def test_lexical_fallback_returns_degraded_results_when_chroma_is_unavailable() -> None:
    service, chroma, _bm25 = _service(
        bm25_indexes={
            "standard_chunks_bm25_20260717": [
                BM25Record(
                    document_id="std-bm25",
                    content="vibration inspection checklist",
                    metadata={
                        "standard_version": "20260717",
                        "standard_id": "STD-C",
                        "access_scope": ["global"],
                    },
                )
            ]
        }
    )
    chroma.set_failure("standard_chunks_20260717")

    result = service.search(
        RetrievalQuery(
            corpus="standards",
            text="vibration inspection",
            filters=RetrievalMetadataFilter(access_scopes=("global",)),
        )
    )

    assert result.degraded is True
    assert result.backend_used == "bm25"
    assert result.version_used == "20260717"
    assert [hit.document_id for hit in result.hits] == ["std-bm25"]
