from __future__ import annotations

from pathlib import Path

from rag.vector_store import SimpleVectorStore


class KnowledgeRetriever:
    def __init__(self, knowledge_base_dir: Path) -> None:
        self.knowledge_base_dir = knowledge_base_dir
        self.store = SimpleVectorStore(self._load_documents())

    def _load_documents(self) -> list[tuple[str, str]]:
        if not self.knowledge_base_dir.exists():
            return []
        documents: list[tuple[str, str]] = []
        for path in sorted(self.knowledge_base_dir.glob("*")):
            if path.suffix.lower() not in {".txt", ".md"}:
                continue
            documents.append((path.name, path.read_text(encoding="utf-8")))
        return documents

    def search(self, query: str, top_k: int = 3) -> list[dict]:
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

