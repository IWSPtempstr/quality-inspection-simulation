from __future__ import annotations

from collections import Counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from ai_service.entities.retrieval import RetrievalMetadataFilter


class BM25SearchError(RuntimeError):
    """Raised when a BM25 index cannot be queried safely."""


class BM25Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    content: str
    metadata: dict[str, Any]


class BM25Client(Protocol):
    def search(
        self,
        *,
        index_name: str,
        query_text: str,
        limit: int,
        metadata_filter: RetrievalMetadataFilter,
    ) -> list[tuple[BM25Record, float]]:
        ...


class InMemoryBM25Client:
    def __init__(self, indexes: dict[str, list[BM25Record]] | None = None):
        self._indexes = indexes or {}
        self._failing_indexes: set[str] = set()

    def set_failure(self, index_name: str) -> None:
        self._failing_indexes.add(index_name)

    def search(
        self,
        *,
        index_name: str,
        query_text: str,
        limit: int,
        metadata_filter: RetrievalMetadataFilter,
    ) -> list[tuple[BM25Record, float]]:
        if index_name in self._failing_indexes:
            raise BM25SearchError(f"index unavailable: {index_name}")
        if index_name not in self._indexes:
            raise BM25SearchError(f"index missing: {index_name}")

        query_terms = _tokenize(query_text)
        scored: list[tuple[BM25Record, float]] = []
        for record in self._indexes[index_name]:
            if not metadata_filter.matches(record.metadata):
                continue
            score = _bm25_like_score(query_terms, _tokenize(record.content))
            if score <= 0:
                continue
            scored.append((record, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]


def _tokenize(text: str) -> Counter[str]:
    normalized = [token for token in text.lower().replace("-", " ").split() if token]
    return Counter(normalized)


def _bm25_like_score(query_terms: Counter[str], document_terms: Counter[str]) -> float:
    if not query_terms or not document_terms:
        return 0.0
    score = 0.0
    document_length = sum(document_terms.values())
    for token, q_frequency in query_terms.items():
        term_frequency = document_terms.get(token, 0)
        if term_frequency == 0:
            continue
        score += (term_frequency / document_length) * q_frequency * 10
    return score
