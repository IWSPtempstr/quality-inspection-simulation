from __future__ import annotations

from fastapi import APIRouter, Request

from db.repositories import AgentTraceRepository
from domain.schemas import AgentRunRequest, DataResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


TASK_PERMISSIONS = {
    "create_order": "orders:write",
    "list_orders": "orders:read",
    "query_queue": "schedule:read",
    "analyze_schedule_options": "schedule:read",
    "analyze_exception": "schedule:read",
    "rebuild_queue": "schedule:write",
    "scheduler_heartbeat": "schedule:write",
    "generate_notifications": "schedule:write",
    "query_notifications": "notifications:read",
    "advance_simulation_clock": "execution:write",
    "search_knowledge": "schedule:read",
    "identify_projects": "schedule:read",
}


@router.post("/run", response_model=DataResponse)
def run_agent(payload: AgentRunRequest, request: Request) -> DataResponse:
    permission = TASK_PERMISSIONS.get(payload.task_type, "schedule:read")
    actor = request.app.state.permission_service.require(request, permission)
    try:
        result = request.app.state.agent_graph.run(payload)
    except Exception as exc:
        request.app.state.audit_service.record(
            request,
            action="agent_run_failed",
            target_type="agent_task",
            target_id=payload.task_type,
            detail={"task_type": payload.task_type, "error": str(exc)},
        )
        raise
    request.app.state.audit_service.record(
        request,
        action="agent_run",
        target_type="agent_task",
        target_id=payload.task_type,
        detail={
            "task_type": payload.task_type,
            "payload_keys": sorted(payload.payload.keys()),
            "visited_agents": result.get("visited_agents", []),
        },
    )
    with request.app.state.session_factory() as session:
        AgentTraceRepository(session).create_trace(
            trace=result["trace"],
            task_type=payload.task_type,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            payload_summary={"payload_keys": sorted(payload.payload.keys())},
            result_summary={
                "visited_agents": result.get("visited_agents", []),
                "error_count": len(result.get("errors", [])),
            },
        )
    return DataResponse(message="Agent任务执行完成", data=result)


@router.get("/configs", response_model=DataResponse)
def get_agent_configs(request: Request) -> DataResponse:
    return DataResponse(
        message="Agent配置查询成功",
        data=request.app.state.agent_graph.public_agent_configs(),
    )
