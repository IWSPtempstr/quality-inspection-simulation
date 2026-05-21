from __future__ import annotations

import re
from dataclasses import dataclass


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}")


def tokenize(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text)}


@dataclass
class KnowledgeDocument:
    source: str
    content: str
    tokens: set[str]


class SimpleVectorStore:
    """Small local vector-store fallback.

    FAISS is listed as the target dependency, but the current conda
    environment does not include it. This store keeps the retriever API stable
    while remaining deterministic for tests and demos.
    """

    def __init__(self, documents: list[tuple[str, str]]) -> None:
        self.documents = [
            KnowledgeDocument(source=source, content=content, tokens=tokenize(content))
            for source, content in documents
        ]

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        query_tokens = tokenize(query)
        scored: list[dict] = []
        for document in self.documents:
            overlap = query_tokens & document.tokens
            score = len(overlap) / max(len(query_tokens), 1)
            if score > 0:
                scored.append(
                    {
                        "source": document.source,
                        "content": document.content,
                        "score": score,
                    }
                )
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:top_k]

