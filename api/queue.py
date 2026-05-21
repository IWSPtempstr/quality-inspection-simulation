from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.dependencies import get_db
from db.repositories import OrderRepository
from domain.schemas import DataResponse

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.get("", response_model=DataResponse)
def get_queue(request: Request) -> DataResponse:
    return DataResponse(message="队列查询成功", data=request.app.state.queue_service.snapshot())


@router.post("/rebuild", response_model=DataResponse)
def rebuild_queue(request: Request, session: Session = Depends(get_db)) -> DataResponse:
    orders = OrderRepository(session).list_active()
    schedule = request.app.state.queue_service.rebuild_schedule(orders)
    return DataResponse(message="队列重建成功", data=schedule)

