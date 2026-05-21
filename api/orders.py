from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_db
from db.repositories import OrderRepository
from domain.schemas import DataResponse, OrderCreate, OrderUpdate

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("", response_model=DataResponse, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, session: Session = Depends(get_db)) -> DataResponse:
    order = OrderRepository(session).create(payload)
    return DataResponse(message="订单创建成功", data=order.model_dump(mode="json"))


@router.get("/{order_id}", response_model=DataResponse)
def get_order(order_id: str, session: Session = Depends(get_db)) -> DataResponse:
    order = OrderRepository(session).get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return DataResponse(message="订单查询成功", data=order.model_dump(mode="json"))


@router.patch("/{order_id}", response_model=DataResponse)
def update_order(order_id: str, payload: OrderUpdate, session: Session = Depends(get_db)) -> DataResponse:
    order = OrderRepository(session).update(order_id, payload)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return DataResponse(message="订单更新成功", data=order.model_dump(mode="json"))


@router.delete("/{order_id}", response_model=DataResponse)
def cancel_order(order_id: str, session: Session = Depends(get_db)) -> DataResponse:
    cancelled = OrderRepository(session).cancel(order_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="订单不存在")
    return DataResponse(message="订单已取消", data={"order_id": order_id, "cancelled": True})

