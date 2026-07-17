from __future__ import annotations

from dataclasses import dataclass

from ai_service.clients.bm25 import BM25Client
from ai_service.clients.chroma import ChromaClient
from ai_service.entities.retrieval import (
    RetrievalActivation,
    RetrievalBackend,
    RetrievalHit,
    RetrievalQuery,
)


@dataclass(frozen=True)
class VersionedRetrievalRepository:
    chroma_client: ChromaClient
    bm25_client: BM25Client
    chroma_prefixes: dict[str, str]
    bm25_prefixes: dict[str, str]

    def vector_search(self, *, version: str, query: RetrievalQuery) -> list[RetrievalHit]:
        collection_name = self._resource_name(
            prefixes=self.chroma_prefixes,
            corpus=query.corpus,
            version=version,
        )
        matches = self.chroma_client.search(
            collection_name=collection_name,
            query_text=query.text,
            limit=query.limit,
            metadata_filter=query.filters,
        )
        return [
            self._to_hit(
                document_id=record.document_id,
                content=record.content,
                metadata=record.metadata,
                score=score,
                backend="chroma",
                version=version,
            )
            for record, score in matches
        ]

    def lexical_search(self, *, version: str, query: RetrievalQuery) -> list[RetrievalHit]:
        index_name = self._resource_name(
            prefixes=self.bm25_prefixes,
            corpus=query.corpus,
            version=version,
        )
        matches = self.bm25_client.search(
            index_name=index_name,
            query_text=query.text,
            limit=query.limit,
            metadata_filter=query.filters,
        )
        return [
            self._to_hit(
                document_id=record.document_id,
                content=record.content,
                metadata=record.metadata,
                score=score,
                backend="bm25",
                version=version,
            )
            for record, score in matches
        ]

    def _resource_name(self, *, prefixes: dict[str, str], corpus: str, version: str) -> str:
        prefix = prefixes[corpus]
        return f"{prefix}_{version}"

    def _to_hit(
        self,
        *,
        document_id: str,
        content: str,
        metadata: dict[str, object],
        score: float,
        backend: RetrievalBackend,
        version: str,
    ) -> RetrievalHit:
        return RetrievalHit(
            document_id=document_id,
            content=content,
            metadata=metadata,
            score=score,
            backend=backend,
            version=version,
        )


class InMemoryActivationRepository:
    def __init__(self, activations: dict[str, RetrievalActivation]):
        self._activations = activations

    def get_activation(self, corpus: str) -> RetrievalActivation:
        return self._activations[corpus]

