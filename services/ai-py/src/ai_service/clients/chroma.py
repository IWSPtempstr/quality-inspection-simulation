from __future__ import annotations

from collections import Counter
from math import sqrt
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from ai_service.entities.retrieval import RetrievalMetadataFilter


class ChromaSearchError(RuntimeError):
    """Raised when a Chroma collection cannot be queried safely."""


class ChromaRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    content: str
    metadata: dict[str, Any]


class ChromaClient(Protocol):
    def search(
        self,
        *,
        collection_name: str,
        query_text: str,
        limit: int,
        metadata_filter: RetrievalMetadataFilter,
    ) -> list[tuple[ChromaRecord, float]]:
        ...


class InMemoryChromaClient:
    def __init__(self, collections: dict[str, list[ChromaRecord]] | None = None):
        self._collections = collections or {}
        self._failing_collections: set[str] = set()

    def set_failure(self, collection_name: str) -> None:
        self._failing_collections.add(collection_name)

    def search(
        self,
        *,
        collection_name: str,
        query_text: str,
        limit: int,
        metadata_filter: RetrievalMetadataFilter,
    ) -> list[tuple[ChromaRecord, float]]:
        if collection_name in self._failing_collections:
            raise ChromaSearchError(f"collection unavailable: {collection_name}")
        if collection_name not in self._collections:
            raise ChromaSearchError(f"collection missing: {collection_name}")

        query_terms = _tokenize(query_text)
        scored: list[tuple[ChromaRecord, float]] = []
        for record in self._collections[collection_name]:
            if not metadata_filter.matches(record.metadata):
                continue
            score = _cosine_overlap(query_terms, _tokenize(record.content))
            if score <= 0:
                continue
            scored.append((record, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def replace_records(
        self,
        *,
        collection_name: str,
        document_id_prefix: str,
        records: list[ChromaRecord],
    ) -> None:
        existing = [
            record
            for record in self._collections.get(collection_name, [])
            if not record.document_id.startswith(document_id_prefix)
        ]
        self._collections[collection_name] = [*existing, *records]

    def delete_records(
        self,
        *,
        collection_name: str,
        document_id_prefix: str,
    ) -> None:
        if collection_name not in self._collections:
            return
        self._collections[collection_name] = [
            record
            for record in self._collections[collection_name]
            if not record.document_id.startswith(document_id_prefix)
        ]


def _tokenize(text: str) -> Counter[str]:
    normalized = [token for token in text.lower().replace("-", " ").split() if token]
    return Counter(normalized)


def _cosine_overlap(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left).intersection(right)
    numerator = sum(left[token] * right[token] for token in shared)
    left_norm = sqrt(sum(value * value for value in left.values()))
    right_norm = sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
