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


@router.post("/reindex", response_model=DataResponse)
def reindex_knowledge(request: Request) -> DataResponse:
    return DataResponse(
        message="知识库重建成功",
        data=request.app.state.knowledge_retriever.reindex(),
    )


@router.get("/status", response_model=DataResponse)
def knowledge_status(request: Request) -> DataResponse:
    return DataResponse(
        message="知识库状态查询成功",
        data=request.app.state.knowledge_retriever.status(),
    )
