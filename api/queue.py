from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.dependencies import get_db
from db.repositories import ScheduleRepository
from domain.schemas import DataResponse, SchedulingEventCreate
from services.schedule_formatter import format_schedule_detail

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.get("", response_model=DataResponse)
def get_queue(request: Request, session: Session = Depends(get_db)) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    repository = ScheduleRepository(session)
    latest = repository.latest()
    if latest:
        detail = repository.get(latest["id"])
        if detail:
            data = format_schedule_detail(detail)
            data["run_id"] = data["id"]
            return DataResponse(message="队列查询成功", data=data)
    return DataResponse(message="队列查询成功", data=request.app.state.queue_service.snapshot())


@router.post("/rebuild", response_model=DataResponse)
def rebuild_queue(request: Request, session: Session = Depends(get_db)) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:write")
    event = request.app.state.scheduling_event_service.record_event(
        SchedulingEventCreate(
            event_type="manual_rebuild_requested",
            severity="high",
            entity_type="system",
            entity_id="queue",
            payload={"source": "api"},
            source="api",
        )
    )
    result = request.app.state.scheduling_coordinator.rebuild(
        trigger_source="api",
        extra_payload={"event_id": event["id"]},
    )
    data = format_schedule_detail(result["run"])
    data["run_id"] = data["id"]
    request.app.state.audit_service.record(
        request,
        action="queue_rebuilt",
        target_type="schedule_run",
        target_id=data["run_id"],
        detail={
            "selected_strategy": result["analysis"].get("selected_strategy"),
            "event_id": event["id"],
        },
    )
    return DataResponse(message="队列重建成功", data=data)
