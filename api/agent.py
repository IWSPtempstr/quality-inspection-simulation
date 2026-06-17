from __future__ import annotations

from fastapi import APIRouter, Request

from db.repositories import AgentSessionRepository, AgentTraceRepository
from domain.schemas import AgentRunRequest, DataResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


TASK_PERMISSIONS = {
    "create_order": "orders:write",
    "list_orders": "orders:read",
    "draft_order_from_text": "orders:read",
    "query_queue": "schedule:read",
    "analyze_schedule_options": "schedule:read",
    "explain_schedule": "schedule:read",
    "analyze_exception": "schedule:read",
    "route_user_query": "schedule:read",
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
    session_context = None
    session_context_used = False
    run_payload = payload
    if payload.session_id and payload.use_session_context:
        with request.app.state.session_factory() as session:
            session_context = AgentSessionRepository(session).get_active(payload.session_id)
        if session_context:
            session_context_used = True
            enriched_payload = dict(payload.payload)
            enriched_payload["_session_context"] = {
                "last_task_type": session_context.get("last_task_type"),
                "last_trace_id": session_context.get("last_trace_id"),
                "summary": session_context.get("summary", {}),
            }
            run_payload = AgentRunRequest(
                task_type=payload.task_type,
                payload=enriched_payload,
                session_id=payload.session_id,
                use_session_context=payload.use_session_context,
            )
    try:
        result = request.app.state.agent_graph.run(run_payload)
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
        target_id=run_payload.task_type,
        detail={
            "task_type": run_payload.task_type,
            "payload_keys": sorted(payload.payload.keys()),
            "visited_agents": result.get("visited_agents", []),
            "session_id": payload.session_id,
            "session_context_used": session_context_used,
        },
    )
    with request.app.state.session_factory() as session:
        AgentTraceRepository(session).create_trace(
            trace=result["trace"],
            task_type=run_payload.task_type,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            payload_summary={"payload_keys": sorted(payload.payload.keys())},
            result_summary={
                "visited_agents": result.get("visited_agents", []),
                "error_count": len(result.get("errors", [])),
            },
        )
        if payload.session_id:
            stored_session = AgentSessionRepository(session).upsert_summary(
                session_id=payload.session_id,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                summary=_structured_session_summary(result),
                last_task_type=payload.task_type,
                last_trace_id=result["trace"]["trace_id"],
            )
            result["session_id"] = payload.session_id
            result["session_context_used"] = session_context_used
            if session_context_used:
                result["session_context"] = {
                    "last_task_type": session_context.get("last_task_type"),
                    "last_trace_id": session_context.get("last_trace_id"),
                    "summary": session_context.get("summary", {}),
                }
            else:
                result["session_context"] = None
            result["session"] = stored_session
    return DataResponse(message="Agent任务执行完成", data=result)


@router.get("/configs", response_model=DataResponse)
def get_agent_configs(request: Request) -> DataResponse:
    return DataResponse(
        message="Agent配置查询成功",
        data=request.app.state.agent_graph.public_agent_configs(),
    )


@router.get("/sessions/{session_id}", response_model=DataResponse)
def get_agent_session(session_id: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    with request.app.state.session_factory() as session:
        result = AgentSessionRepository(session).get(session_id)
    if result is None:
        return DataResponse(message="Agent Session 不存在", data=None)
    return DataResponse(message="Agent Session 查询成功", data=result)


@router.delete("/sessions/{session_id}", response_model=DataResponse)
def close_agent_session(session_id: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    with request.app.state.session_factory() as session:
        result = AgentSessionRepository(session).close(session_id)
    if result is None:
        return DataResponse(message="Agent Session 不存在", data=None)
    return DataResponse(message="Agent Session 已关闭", data=result)


def _structured_session_summary(agent_result: dict) -> dict:
    result = agent_result.get("result", {})
    summary: dict = {}
    if isinstance(result, dict):
        for key in (
            "order_draft",
            "missing_fields",
            "recommended_task_type",
            "target_agent",
            "confidence",
            "summary",
            "sla_risks",
            "bottlenecks",
            "recommended_projects",
            "required_projects",
            "risk_notes",
        ):
            if key in result:
                summary[key] = result[key]
    return summary
