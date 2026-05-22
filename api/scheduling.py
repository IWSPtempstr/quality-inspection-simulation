from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from db.repositories import SchedulingEventRepository
from domain.schemas import DataResponse, SchedulingEventCreate, SchedulingEventResolve, utc_now

router = APIRouter(prefix="/api/scheduling", tags=["scheduling"])


@router.post("/events", response_model=DataResponse, status_code=status.HTTP_201_CREATED)
def create_scheduling_event(payload: SchedulingEventCreate, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:write")
    event = request.app.state.scheduling_event_service.record_event(payload)
    if request.app.state.scheduling_event_service.should_trigger_immediately(event):
        heartbeat = request.app.state.scheduler_heartbeat_service.trigger()
        refreshed = request.app.state.scheduling_event_service.list_events(
            event_type=event["event_type"],
            entity_type=event.get("entity_type"),
            entity_id=event.get("entity_id"),
        )
        event = next((item for item in refreshed if item["id"] == event["id"]), event)
        event["immediate_heartbeat"] = heartbeat
    request.app.state.audit_service.record(
        request,
        action="scheduling_event_created",
        target_type="scheduling_event",
        target_id=event["id"],
        detail={"event_type": event["event_type"], "severity": event["severity"]},
    )
    return DataResponse(message="排程事件已写入", data=event)


@router.get("/events", response_model=DataResponse)
def list_scheduling_events(
    request: Request,
    status: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
) -> DataResponse:
    events = request.app.state.scheduling_event_service.list_events(
        status=status,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return DataResponse(message="排程事件查询成功", data=events)


@router.post("/heartbeat", response_model=DataResponse)
def trigger_scheduler_heartbeat(request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:write")
    result = request.app.state.scheduler_heartbeat_service.trigger()
    request.app.state.audit_service.record(
        request,
        action="scheduler_heartbeat_triggered",
        target_type="scheduler",
        target_id=result.get("schedule_run_id"),
        detail={"triggered": result.get("triggered"), "reason": result.get("reason")},
    )
    return DataResponse(
        message="排程心跳处理完成",
        data=result,
    )


@router.get("/heartbeat/status", response_model=DataResponse)
def scheduler_heartbeat_status(request: Request) -> DataResponse:
    return DataResponse(
        message="排程心跳状态查询成功",
        data=request.app.state.scheduler_heartbeat_service.status(),
    )


@router.patch("/events/{event_id}/resolve", response_model=DataResponse)
def resolve_scheduling_event(event_id: str, payload: SchedulingEventResolve, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "events:resolve")
    with request.app.state.session_factory() as session:
        event = SchedulingEventRepository(session).resolve(
            event_id=event_id,
            status=payload.status,
            now=utc_now(),
            resolution_note=payload.resolution_note,
        )
    if event is None:
        raise HTTPException(status_code=404, detail="排程事件不存在")
    request.app.state.audit_service.record(
        request,
        action="scheduling_event_resolved",
        target_type="scheduling_event",
        target_id=event_id,
        detail={"status": payload.status.value, "resolution_note": payload.resolution_note},
    )
    return DataResponse(message="排程事件已闭环", data=event)
