from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_service.entities.retrieval import RetrievalHit


class RerankerUnavailableError(RuntimeError):
    """Raised when the local Cross-Encoder cannot score candidates."""


class CrossEncoderReranker(Protocol):
    def rerank(self, *, query_text: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        ...


@dataclass(frozen=True)
class HeuristicCrossEncoderReranker:
    available: bool = True

    def rerank(self, *, query_text: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        if not self.available:
            raise RerankerUnavailableError("cross-encoder unavailable")

        query_terms = {token for token in query_text.lower().replace("-", " ").split() if token}
        ranked = sorted(
            hits,
            key=lambda hit: (
                -_overlap_count(query_terms, hit.content),
                -hit.score,
                hit.document_id,
            ),
        )
        return ranked


def _overlap_count(query_terms: set[str], content: str) -> int:
    content_terms = {token for token in content.lower().replace("-", " ").split() if token}
    return len(query_terms.intersection(content_terms))
