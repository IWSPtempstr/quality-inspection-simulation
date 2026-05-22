from __future__ import annotations

from fastapi import APIRouter, Request

from domain.schemas import DataResponse, SimulationClockAdvanceRequest

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.get("/clock", response_model=DataResponse)
def get_simulation_clock(request: Request) -> DataResponse:
    return DataResponse(message="仿真时钟查询成功", data=request.app.state.notification_service.clock())


@router.post("/clock/advance", response_model=DataResponse)
def advance_simulation_clock(payload: SimulationClockAdvanceRequest, request: Request) -> DataResponse:
    return DataResponse(
        message="仿真时钟已推进",
        data=request.app.state.notification_service.advance_clock(
            current_time=payload.current_time,
            delta_minutes=payload.delta_minutes,
        ),
    )
