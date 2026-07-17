"""Repository placeholders for future bounded read-only adapters."""

from ai_service.repositories.retrieval import (
    InMemoryActivationRepository,
    VersionedRetrievalRepository,
)

__all__ = ["InMemoryActivationRepository", "VersionedRetrievalRepository"]
