from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.dependencies import get_db
from db.repositories import OrderRepository
from domain.schemas import DataResponse, OrderCreate, OrderUpdate, RetestCreate

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("", response_model=DataResponse, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, request: Request, session: Session = Depends(get_db)) -> DataResponse:
    request.app.state.permission_service.require(request, "orders:write")
    order = OrderRepository(session).create(payload)
    request.app.state.scheduling_event_service.create_order_event(
        order.model_dump(mode="json"),
        "order_created",
    )
    request.app.state.audit_service.record(
        request,
        action="order_created",
        target_type="order",
        target_id=order.id,
        detail=order.model_dump(mode="json"),
    )
    return DataResponse(message="订单创建成功", data=order.model_dump(mode="json"))


@router.get("/{order_id}", response_model=DataResponse)
def get_order(order_id: str, session: Session = Depends(get_db)) -> DataResponse:
    order = OrderRepository(session).get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return DataResponse(message="订单查询成功", data=order.model_dump(mode="json"))


@router.patch("/{order_id}", response_model=DataResponse)
def update_order(order_id: str, payload: OrderUpdate, request: Request, session: Session = Depends(get_db)) -> DataResponse:
    request.app.state.permission_service.require(request, "orders:write")
    repository = OrderRepository(session)
    existing = repository.get(order_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    changes = payload.model_dump(mode="json", exclude_unset=True)
    order = repository.update(order_id, payload)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if changes:
        request.app.state.scheduling_event_service.create_update_event(
            order.model_dump(mode="json"),
            changes,
        )
        request.app.state.audit_service.record(
            request,
            action="order_updated",
            target_type="order",
            target_id=order_id,
            detail={"changes": changes},
        )
    return DataResponse(message="订单更新成功", data=order.model_dump(mode="json"))


@router.delete("/{order_id}", response_model=DataResponse)
def cancel_order(order_id: str, request: Request, session: Session = Depends(get_db)) -> DataResponse:
    request.app.state.permission_service.require(request, "orders:write")
    repository = OrderRepository(session)
    order = repository.get(order_id)
    cancelled = repository.cancel(order_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order is not None:
        request.app.state.scheduling_event_service.create_order_event(
            order.model_dump(mode="json"),
            "order_cancelled",
        )
        request.app.state.audit_service.record(
            request,
            action="order_cancelled",
            target_type="order",
            target_id=order_id,
            detail={"previous_status": order.status.value},
        )
    return DataResponse(message="订单已取消", data={"order_id": order_id, "cancelled": True})


@router.post("/{order_id}/retest", response_model=DataResponse, status_code=status.HTTP_201_CREATED)
def create_retest_order(
    order_id: str,
    payload: RetestCreate,
    request: Request,
    session: Session = Depends(get_db),
) -> DataResponse:
    request.app.state.permission_service.require(request, "orders:write")
    repository = OrderRepository(session)
    original = repository.get(order_id)
    if original is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    retest_order = repository.create_retest(
        original=original,
        reason=payload.reason,
        requested_projects=payload.requested_projects,
        promised_finish_time=payload.promised_finish_time,
    )
    request.app.state.scheduling_event_service.create_order_event(
        retest_order.model_dump(mode="json"),
        "retest_required",
    )
    request.app.state.audit_service.record(
        request,
        action="retest_created",
        target_type="order",
        target_id=retest_order.id,
        detail={"parent_order_id": order_id, "reason": payload.reason},
    )
    return DataResponse(message="复检订单已创建", data=retest_order.model_dump(mode="json"))
