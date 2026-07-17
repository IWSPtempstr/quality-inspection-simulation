from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_service.clients.reranker import RerankerUnavailableError
from ai_service.core.context import RequestContext
from ai_service.entities.models import Citation, KnowledgeAnswer, KnowledgeQuery, StrictModel
from ai_service.entities.retrieval import HybridRetrievalResult, RetrievalHit, RetrievalQuery
from ai_service.services.retrieval import RetrievalService


class KnowledgeImpactItem(StrictModel):
    standard_title: str
    version: str
    clause: str
    page: int
    content: str
    impact: str


class KnowledgeImpactAnalysis(StrictModel):
    summary: str
    findings: list[KnowledgeImpactItem]
    evidence_available: bool
    degraded: bool


class SupportsReranking(Protocol):
    def rerank(self, *, query_text: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        ...


@dataclass(frozen=True)
class KnowledgeService:
    retrieval_service: RetrievalService
    reranker: SupportsReranking

    def answer(self, *, payload: KnowledgeQuery, context: RequestContext) -> KnowledgeAnswer:
        _ = context
        retrieval_result = build_hybrid_retrieval(
            retrieval_service=self.retrieval_service,
            reranker=self.reranker,
            query=self._retrieval_query(payload, limit=50),
        )
        citations = self._citations_from_hits(retrieval_result.hits[:5])
        if not citations:
            return KnowledgeAnswer(
                answer="No cited standards are currently available for this query.",
                citations=[],
                evidence_available=False,
            )

        degraded_text = (
            " Degraded retrieval or reranking fallback was used."
            if retrieval_result.degraded
            else ""
        )
        answer = (
            f"Relevant cited standards were found for {payload.query!r}.{degraded_text}"
            f" Top evidence: {self._answer_snippets(citations)}"
        ).strip()
        return KnowledgeAnswer(
            answer=answer,
            citations=citations,
            evidence_available=True,
        )

    def analyze_impact(
        self,
        *,
        payload: KnowledgeQuery,
        context: RequestContext,
    ) -> KnowledgeImpactAnalysis:
        _ = context
        retrieval_result = build_hybrid_retrieval(
            retrieval_service=self.retrieval_service,
            reranker=self.reranker,
            query=self._retrieval_query(payload, limit=50),
        )
        citations = self._citations_from_hits(retrieval_result.hits[:5])
        if not citations:
            return KnowledgeImpactAnalysis(
                summary="No cited standards are currently available for impact analysis.",
                findings=[],
                evidence_available=False,
                degraded=True,
            )

        findings = [
            KnowledgeImpactItem(
                standard_title=citation.standard_title,
                version=citation.version,
                clause=citation.clause,
                page=citation.page,
                content=citation.content,
                impact=self._impact_label(payload.query, citation),
            )
            for citation in citations
        ]
        degraded = retrieval_result.degraded
        summary = f"Impact analysis identified {len(findings)} cited standard clauses."
        if degraded:
            summary += " Degraded retrieval or reranking fallback was used."
        return KnowledgeImpactAnalysis(
            summary=summary,
            findings=findings,
            evidence_available=True,
            degraded=degraded,
        )

    def _retrieval_query(self, payload: KnowledgeQuery, *, limit: int) -> RetrievalQuery:
        return RetrievalQuery(
            corpus="standards",
            text=payload.query,
            limit=limit,
        )

    def _citations_from_hits(self, hits: list[RetrievalHit]) -> list[Citation]:
        citations: list[Citation] = []
        for hit in hits:
            metadata = hit.metadata
            standard_title = metadata.get("standard_title")
            version = metadata.get("standard_version")
            clause = metadata.get("clause")
            page = metadata.get("page")
            if not (
                isinstance(standard_title, str)
                and isinstance(version, str)
                and isinstance(clause, str)
                and isinstance(page, int)
                and page >= 1
            ):
                continue
            citations.append(
                Citation(
                    standard_title=standard_title,
                    version=version,
                    clause=clause,
                    page=page,
                    content=hit.content,
                )
            )
        return citations

    def _answer_snippets(self, citations: list[Citation]) -> str:
        snippets = [
            f"{citation.standard_title} {citation.clause} p.{citation.page}: {citation.content}"
            for citation in citations[:3]
        ]
        return " | ".join(snippets)

    def _impact_label(self, query_text: str, citation: Citation) -> str:
        query_terms = set(query_text.lower().replace("-", " ").split())
        content_terms = set(citation.content.lower().replace("-", " ").split())
        shared = query_terms.intersection(content_terms)
        if len(shared) >= 2:
            return "direct"
        if shared:
            return "related"
        return "background"


def build_hybrid_retrieval(
    *,
    retrieval_service: RetrievalService,
    reranker: SupportsReranking,
    query: RetrievalQuery,
) -> HybridRetrievalResult:
    result = retrieval_service.hybrid_search(query)
    candidates = result.hits[:20]
    if not candidates:
        return result
    try:
        reranked_hits = reranker.rerank(query_text=query.text, hits=candidates)
    except RerankerUnavailableError as exc:
        return HybridRetrievalResult(
            corpus=result.corpus,
            hits=result.hits[:5],
            degraded=True,
            degradation_reasons=[*result.degradation_reasons, str(exc)],
            version_used=result.version_used,
            vector_backend_available=result.vector_backend_available,
            lexical_backend_available=result.lexical_backend_available,
        )

    return HybridRetrievalResult(
        corpus=result.corpus,
        hits=[*reranked_hits[:20], *result.hits[20:]][:5],
        degraded=result.degraded,
        degradation_reasons=result.degradation_reasons,
        version_used=result.version_used,
        vector_backend_available=result.vector_backend_available,
        lexical_backend_available=result.lexical_backend_available,
    )
