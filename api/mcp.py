from __future__ import annotations

from fastapi import APIRouter, Request

from domain.schemas import DataResponse

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/status", response_model=DataResponse)
def mcp_status(request: Request) -> DataResponse:
    return DataResponse(
        message="MCP 状态查询成功",
        data=request.app.state.tool_client.status(),
    )

