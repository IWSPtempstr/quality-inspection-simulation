from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class DeterministicEmbeddingProvider:
    name = "deterministic-fallback"

    def __init__(self, dimensions: int = 128) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector = vector / norm
        return vector.tolist()


class OpenAICompatibleEmbeddingProvider:
    name = "openai-compatible"

    def __init__(self, api_key: str, base_url: str | None, model: str) -> None:
        from langchain_openai import OpenAIEmbeddings

        self.model = model
        self._embeddings = OpenAIEmbeddings(
            model=model,
            api_key=api_key,
            base_url=base_url,
            check_embedding_ctx_length=False,
        )
        self.dimensions = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._embeddings.embed_documents(texts)
        if vectors and self.dimensions == 0:
            self.dimensions = len(vectors[0])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vector = self._embeddings.embed_query(text)
        if vector and self.dimensions == 0:
            self.dimensions = len(vector)
        return vector


@dataclass
class KnowledgeDocument:
    source: str
    content: str


class FaissVectorStore:
    """Persisted vector index with FAISS when available and numpy fallback otherwise."""

    def __init__(self, index_dir: Path, embedding_provider: EmbeddingProvider) -> None:
        self.index_dir = index_dir
        self.embedding_provider = embedding_provider
        self.documents: list[KnowledgeDocument] = []
        self.vectors: np.ndarray | None = None
        self._faiss_index = None
        self.backend = "numpy"
        try:
            import faiss  # type: ignore

            self._faiss = faiss
            self.backend = "faiss"
        except Exception:
            self._faiss = None

    @property
    def metadata_path(self) -> Path:
        return self.index_dir / "metadata.json"

    @property
    def vectors_path(self) -> Path:
        return self.index_dir / "vectors.npy"

    @property
    def faiss_path(self) -> Path:
        return self.index_dir / "index.faiss"

    def exists(self) -> bool:
        if self.backend == "faiss":
            return self.metadata_path.exists() and self.faiss_path.exists()
        return self.metadata_path.exists() and self.vectors_path.exists()

    def build(self, documents: list[tuple[str, str]]) -> dict:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.documents = [KnowledgeDocument(source=source, content=content) for source, content in documents]
        texts = [document.content for document in self.documents]
        raw_vectors = self.embedding_provider.embed_documents(texts) if texts else []
        self.vectors = self._normalize(np.array(raw_vectors, dtype=np.float32)) if raw_vectors else np.zeros((0, 0))
        self._write_index()
        self._write_metadata()
        return self.status()

    def load(self) -> bool:
        if not self.metadata_path.exists():
            return False
        metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        if metadata.get("embedding_provider") != self.embedding_provider.name:
            self.documents = []
            self.vectors = None
            self._faiss_index = None
            return False
        self.documents = [
            KnowledgeDocument(source=item["source"], content=item["content"])
            for item in metadata.get("documents", [])
        ]
        if self.backend == "faiss" and self.faiss_path.exists():
            self._faiss_index = self._faiss.read_index(str(self.faiss_path))
            return True
        if self.vectors_path.exists():
            self.vectors = np.load(self.vectors_path)
            return True
        return False

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if not self.documents:
            self.load()
        if not self.documents:
            return []
        query_vector = self._normalize(np.array([self.embedding_provider.embed_query(query)], dtype=np.float32))
        if self.backend == "faiss" and self._faiss_index is not None:
            scores, indices = self._faiss_index.search(query_vector, min(top_k, len(self.documents)))
            pairs = zip(indices[0].tolist(), scores[0].tolist(), strict=False)
        else:
            if self.vectors is None:
                self.load()
            if self.vectors is None or self.vectors.size == 0:
                return []
            scores = np.dot(self.vectors, query_vector[0])
            ranked = np.argsort(scores)[::-1][:top_k]
            pairs = [(int(index), float(scores[index])) for index in ranked]

        results = []
        for index, score in pairs:
            if index < 0 or index >= len(self.documents):
                continue
            if score <= 0:
                continue
            document = self.documents[index]
            results.append({"source": document.source, "content": document.content, "score": float(score)})
        return results

    def status(self) -> dict:
        return {
            "backend": self.backend,
            "embedding_provider": self.embedding_provider.name,
            "document_count": len(self.documents),
            "index_exists": self.exists(),
            "index_dir": str(self.index_dir),
            "sources": [document.source for document in self.documents],
        }

    def _write_index(self) -> None:
        if self.vectors is None:
            return
        if self.backend == "faiss" and self.vectors.size > 0:
            index = self._faiss.IndexFlatIP(self.vectors.shape[1])
            index.add(self.vectors)
            self._faiss.write_index(index, str(self.faiss_path))
            self._faiss_index = index
            return
        np.save(self.vectors_path, self.vectors)

    def _write_metadata(self) -> None:
        metadata = {
            "backend": self.backend,
            "embedding_provider": self.embedding_provider.name,
            "documents": [
                {"source": document.source, "content": document.content}
                for document in self.documents
            ],
        }
        self.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize(self, vectors: np.ndarray) -> np.ndarray:
        if vectors.size == 0:
            return vectors
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms
