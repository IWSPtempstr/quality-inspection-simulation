from __future__ import annotations

from fastapi import APIRouter, Request

from domain.schemas import AgentRunRequest, DataResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/run", response_model=DataResponse)
def run_agent(payload: AgentRunRequest, request: Request) -> DataResponse:
    return DataResponse(message="Agent任务执行完成", data=request.app.state.agent_graph.run(payload))


@router.get("/configs", response_model=DataResponse)
def get_agent_configs(request: Request) -> DataResponse:
    return DataResponse(
        message="Agent配置查询成功",
        data=request.app.state.agent_graph.public_agent_configs(),
    )
