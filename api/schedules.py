from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db
from db.repositories import ScheduleRepository
from domain.schemas import DataResponse
from services.schedule_formatter import format_schedule_detail, format_schedule_summary

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("", response_model=DataResponse)
def list_schedules(session: Session = Depends(get_db)) -> DataResponse:
    repository = ScheduleRepository(session)
    return DataResponse(
        message="排程列表查询成功",
        data=[format_schedule_summary(item) for item in repository.list_runs()],
    )


@router.get("/{run_id}", response_model=DataResponse)
def get_schedule(run_id: str, session: Session = Depends(get_db)) -> DataResponse:
    repository = ScheduleRepository(session)
    schedule = repository.get(run_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="排程不存在")
    return DataResponse(message="排程详情查询成功", data=format_schedule_detail(schedule))
