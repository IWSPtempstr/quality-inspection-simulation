"""External protocol adapters."""

from ai_service.clients.bm25 import BM25Record, BM25SearchError, InMemoryBM25Client
from ai_service.clients.chroma import ChromaRecord, ChromaSearchError, InMemoryChromaClient
from ai_service.clients.llm_gateway import (
    DisabledLLMGateway,
    GatewayPrompt,
    LLMGateway,
    LLMGatewayDisabled,
    NormalizedLLMResponse,
    StructuredLLMGateway,
    normalize_json_payload,
)
from ai_service.clients.redis_memory import InMemoryRedisClient
from ai_service.clients.reranker import (
    HeuristicCrossEncoderReranker,
    RerankerUnavailableError,
)

__all__ = [
    "BM25Record",
    "BM25SearchError",
    "ChromaRecord",
    "ChromaSearchError",
    "DisabledLLMGateway",
    "GatewayPrompt",
    "InMemoryBM25Client",
    "InMemoryChromaClient",
    "LLMGateway",
    "LLMGatewayDisabled",
    "NormalizedLLMResponse",
    "InMemoryRedisClient",
    "HeuristicCrossEncoderReranker",
    "StructuredLLMGateway",
    "RerankerUnavailableError",
    "normalize_json_payload",
]
