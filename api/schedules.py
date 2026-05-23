from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.dependencies import get_db
from db.repositories import ScheduleRepository
from domain.schemas import DataResponse, SchedulingEventCreate, StepExecutionUpdate, utc_now
from services.schedule_formatter import format_gantt, format_schedule_detail, format_schedule_summary

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("", response_model=DataResponse)
def list_schedules(request: Request, session: Session = Depends(get_db)) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    repository = ScheduleRepository(session)
    return DataResponse(
        message="排程列表查询成功",
        data=[format_schedule_summary(item) for item in repository.list_runs()],
    )


@router.get("/{run_id}", response_model=DataResponse)
def get_schedule(run_id: str, request: Request, session: Session = Depends(get_db)) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    repository = ScheduleRepository(session)
    schedule = repository.get(run_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="排程不存在")
    return DataResponse(message="排程详情查询成功", data=format_schedule_detail(schedule))


@router.get("/{run_id}/gantt", response_model=DataResponse)
def get_schedule_gantt(run_id: str, request: Request, session: Session = Depends(get_db)) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    repository = ScheduleRepository(session)
    schedule = repository.get(run_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="排程不存在")
    return DataResponse(message="设备预约甘特图查询成功", data=format_gantt(schedule))


@router.patch("/steps/{step_id}/running", response_model=DataResponse)
def mark_step_running(
    step_id: str,
    payload: StepExecutionUpdate,
    request: Request,
    session: Session = Depends(get_db),
) -> DataResponse:
    request.app.state.permission_service.require(request, "execution:write")
    step = ScheduleRepository(session).mark_step_running(
        step_id,
        actual_time=payload.actual_time or utc_now(),
        note=payload.note,
    )
    if step is None:
        raise HTTPException(status_code=404, detail="排程步骤不存在")
    request.app.state.audit_service.record(
        request,
        action="step_started",
        target_type="schedule_step",
        target_id=step_id,
        detail={"order_id": step["order_id"], "note": payload.note},
    )
    return DataResponse(message="检测步骤已标记为运行中", data=step)


@router.patch("/steps/{step_id}/complete", response_model=DataResponse)
def mark_step_completed(
    step_id: str,
    payload: StepExecutionUpdate,
    request: Request,
    session: Session = Depends(get_db),
) -> DataResponse:
    request.app.state.permission_service.require(request, "execution:write")
    step = ScheduleRepository(session).mark_step_completed(
        step_id,
        actual_time=payload.actual_time or utc_now(),
        note=payload.note,
    )
    if step is None:
        raise HTTPException(status_code=404, detail="排程步骤不存在")
    request.app.state.audit_service.record(
        request,
        action="step_completed",
        target_type="schedule_step",
        target_id=step_id,
        detail={"order_id": step["order_id"], "note": payload.note},
    )
    request.app.state.scheduling_event_service.record_event(
        SchedulingEventCreate(
            event_type="detection_completed",
            severity="medium",
            entity_type="schedule_step",
            entity_id=step_id,
            payload={"order_id": step["order_id"], "project_type": step.get("project_type")},
            source="execution_api",
        )
    )
    return DataResponse(message="检测步骤已标记为完成", data=step)
