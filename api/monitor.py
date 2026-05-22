from __future__ import annotations

from fastapi import APIRouter, Request

from domain.schemas import DataResponse

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/snapshot", response_model=DataResponse)
def get_monitor_snapshot(request: Request) -> DataResponse:
    return DataResponse(message="监测快照查询成功", data=request.app.state.queue_service.snapshot())


@router.get("/report", response_model=DataResponse)
def get_monitor_report(request: Request) -> DataResponse:
    return DataResponse(message="监测报告查询成功", data=request.app.state.monitoring_report_service.report())
