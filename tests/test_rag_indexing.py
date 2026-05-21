from pathlib import Path

from rag.retriever import KnowledgeRetriever


def test_reindex_persists_vector_index_and_status(tmp_path, monkeypatch):
    knowledge_dir = tmp_path / "knowledge"
    index_dir = tmp_path / "index"
    knowledge_dir.mkdir()
    (knowledge_dir / "ccc.txt").write_text("CCC 强制性认证包含安全检测和电磁兼容检测。", encoding="utf-8")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    retriever = KnowledgeRetriever(knowledge_dir, index_dir=index_dir)
    status = retriever.reindex()

    assert status["document_count"] == 1
    assert status["index_exists"] is True
    assert (index_dir / "metadata.json").exists()
    assert status["embedding_provider"] == "deterministic-fallback"

    reloaded = KnowledgeRetriever(knowledge_dir, index_dir=index_dir)
    results = reloaded.search("CCC 安全检测", top_k=1)

    assert results[0]["source"] == "ccc.txt"
    assert results[0]["score"] > 0


def test_knowledge_api_reindex_and_status(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    knowledge_dir = tmp_path / "knowledge"
    index_dir = tmp_path / "index"
    knowledge_dir.mkdir()
    (knowledge_dir / "international.txt").write_text("国际认证包含 CB 资料评审。", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(knowledge_dir))
    monkeypatch.setenv("RAG_INDEX_DIR", str(index_dir))
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    from app import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    reindex_response = client.post("/api/knowledge/reindex")
    status_response = client.get("/api/knowledge/status")
    search_response = client.post(
        "/api/knowledge/search",
        json={"query": "国际 CB", "top_k": 1},
    )

    assert reindex_response.status_code == 200
    assert status_response.json()["data"]["index_exists"] is True
    assert search_response.json()["data"][0]["source"] == "international.txt"

