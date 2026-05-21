from __future__ import annotations

from pathlib import Path

from config.settings import get_settings
from rag.vector_store import (
    DeterministicEmbeddingProvider,
    FaissVectorStore,
    OpenAICompatibleEmbeddingProvider,
)


class KnowledgeRetriever:
    def __init__(
        self,
        knowledge_base_dir: Path,
        index_dir: Path | None = None,
        embedding_provider=None,
    ) -> None:
        self.knowledge_base_dir = knowledge_base_dir
        settings = get_settings()
        self.index_dir = index_dir or settings.rag_index_dir
        self.embedding_provider = embedding_provider or self._create_embedding_provider(settings)
        self.store = FaissVectorStore(self.index_dir, self.embedding_provider)
        self.store.load()

    def _load_documents(self) -> list[tuple[str, str]]:
        if not self.knowledge_base_dir.exists():
            return []
        documents: list[tuple[str, str]] = []
        for path in sorted(self.knowledge_base_dir.glob("*")):
            if path.suffix.lower() not in {".txt", ".md"}:
                continue
            documents.append((path.name, path.read_text(encoding="utf-8")))
        return documents

    def reindex(self) -> dict:
        return self.store.build(self._load_documents())

    def status(self) -> dict:
        loaded = self.store.load()
        status = self.store.status()
        status["loaded"] = loaded
        status["knowledge_base_dir"] = str(self.knowledge_base_dir)
        return status

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if not self.store.load():
            self.reindex()
        results = self.store.search(query, top_k)
        if results:
            return results
        return [
            {
                "source": "fallback",
                "content": "未检索到直接匹配的认证规则或设备约束，可补充知识库后重新检索。",
                "score": 0.0,
            }
        ]

    def _create_embedding_provider(self, settings):
        if settings.embedding_provider == "openai-compatible" and settings.embedding_api_key:
            return OpenAICompatibleEmbeddingProvider(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
                model=settings.embedding_model,
            )
        return DeterministicEmbeddingProvider()
