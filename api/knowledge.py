from __future__ import annotations

from fastapi import APIRouter, Request

from domain.schemas import DataResponse, KnowledgeSearchRequest

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("/search", response_model=DataResponse)
def search_knowledge(payload: KnowledgeSearchRequest, request: Request) -> DataResponse:
    return DataResponse(
        message="知识检索成功",
        data=request.app.state.knowledge_retriever.search(payload.query, payload.top_k),
    )

