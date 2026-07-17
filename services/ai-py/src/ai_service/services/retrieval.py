from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_service.clients.bm25 import BM25SearchError
from ai_service.clients.chroma import ChromaSearchError
from ai_service.entities.retrieval import (
    HybridRetrievalResult,
    RetrievalActivation,
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
)
from ai_service.repositories.retrieval import VersionedRetrievalRepository


class ActivationRepository(Protocol):
    def get_activation(self, corpus: str) -> RetrievalActivation:
        ...


@dataclass(frozen=True)
class RetrievalService:
    activation_repository: ActivationRepository
    repository: VersionedRetrievalRepository

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        activation = self.activation_repository.get_activation(query.corpus)
        degradation_reasons: list[str] = []
        for version in self._candidate_versions(
            activation=activation,
            allow_fallback=query.allow_version_fallback,
        ):
            try:
                hits = self.repository.vector_search(version=version, query=query)
            except ChromaSearchError as exc:
                degradation_reasons.append(str(exc))
            else:
                return RetrievalResult(
                    corpus=query.corpus,
                    hits=hits,
                    degraded=bool(degradation_reasons) or version != activation.active_version,
                    degradation_reasons=degradation_reasons,
                    backend_used="chroma",
                    version_used=version,
                )

            try:
                hits = self.repository.lexical_search(version=version, query=query)
            except BM25SearchError as exc:
                degradation_reasons.append(str(exc))
            else:
                return RetrievalResult(
                    corpus=query.corpus,
                    hits=hits,
                    degraded=True,
                    degradation_reasons=degradation_reasons,
                    backend_used="bm25",
                    version_used=version,
                )

        return RetrievalResult(
            corpus=query.corpus,
            hits=[],
            degraded=True,
            degradation_reasons=degradation_reasons or ["no retrieval backend available"],
            backend_used="none",
            version_used=None,
        )

    def hybrid_search(self, query: RetrievalQuery) -> HybridRetrievalResult:
        activation = self.activation_repository.get_activation(query.corpus)
        degradation_reasons: list[str] = []
        expanded_query = query.model_copy(update={"limit": 50})
        for version in self._candidate_versions(
            activation=activation,
            allow_fallback=query.allow_version_fallback,
        ):
            vector_hits: list[RetrievalHit] = []
            lexical_hits: list[RetrievalHit] = []
            vector_available = False
            lexical_available = False

            try:
                vector_hits = self.repository.vector_search(version=version, query=expanded_query)
            except ChromaSearchError as exc:
                degradation_reasons.append(str(exc))
            else:
                vector_available = True

            try:
                lexical_hits = self.repository.lexical_search(version=version, query=expanded_query)
            except BM25SearchError as exc:
                degradation_reasons.append(str(exc))
            else:
                lexical_available = True

            if not vector_available and not lexical_available:
                continue

            fused_hits = self._rrf_fuse(vector_hits, lexical_hits)
            degraded = (
                bool(degradation_reasons)
                or version != activation.active_version
                or not vector_available
                or not lexical_available
            )
            return HybridRetrievalResult(
                corpus=query.corpus,
                hits=fused_hits,
                degraded=degraded,
                degradation_reasons=degradation_reasons,
                version_used=version,
                vector_backend_available=vector_available,
                lexical_backend_available=lexical_available,
            )

        return HybridRetrievalResult(
            corpus=query.corpus,
            hits=[],
            degraded=True,
            degradation_reasons=degradation_reasons or ["no retrieval backend available"],
            version_used=None,
            vector_backend_available=False,
            lexical_backend_available=False,
        )

    def _candidate_versions(
        self,
        *,
        activation: RetrievalActivation,
        allow_fallback: bool,
    ) -> tuple[str, ...]:
        if not allow_fallback:
            return (activation.active_version,)
        return (activation.active_version, *activation.fallback_versions)

    def _rrf_fuse(
        self,
        vector_hits: list[RetrievalHit],
        lexical_hits: list[RetrievalHit],
    ) -> list[RetrievalHit]:
        by_id: dict[str, RetrievalHit] = {}
        scores: dict[str, float] = {}

        for hits in (vector_hits, lexical_hits):
            for rank, hit in enumerate(hits, start=1):
                by_id.setdefault(hit.document_id, hit)
                scores[hit.document_id] = scores.get(hit.document_id, 0.0) + (1.0 / (60 + rank))

        fused = [
            by_id[document_id].model_copy(update={"score": score, "backend": "hybrid"})
            for document_id, score in scores.items()
        ]
        fused.sort(key=lambda hit: (-hit.score, hit.document_id))
        return fused
