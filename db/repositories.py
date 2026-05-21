from __future__ import annotations

import json
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import DetectionProjectModel, EquipmentModel, OrderModel, QueueEventModel
from domain.schemas import (
    CertificationType,
    EquipmentStatus,
    OrderCreate,
    OrderResponse,
    OrderType,
    OrderUpdate,
    QueueStatus,
    new_id,
    utc_now,
)


def _json_dump(value: list[str] | dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def order_to_dict(order: OrderModel) -> dict:
    return {
        "id": order.id,
        "order_type": OrderType(order.order_type),
        "sample_name": order.sample_name,
        "sample_quantity": order.sample_quantity,
        "certification_type": CertificationType(order.certification_type),
        "requested_projects": _json_list(order.requested_projects),
        "status": QueueStatus(order.status),
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


class OrderRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, payload: OrderCreate) -> OrderResponse:
        model = OrderModel(
            id=new_id("order"),
            order_type=payload.order_type.value,
            sample_name=payload.sample_name,
            sample_quantity=payload.sample_quantity,
            certification_type=payload.certification_type.value,
            requested_projects=_json_dump(payload.requested_projects),
            status=QueueStatus.PENDING.value,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return OrderResponse(**order_to_dict(model))

    def list_active(self) -> list[dict]:
        statement = select(OrderModel).where(OrderModel.status != QueueStatus.CANCELLED.value)
        return [order_to_dict(item) for item in self.session.scalars(statement).all()]

    def get(self, order_id: str) -> OrderResponse | None:
        model = self.session.get(OrderModel, order_id)
        return OrderResponse(**order_to_dict(model)) if model else None

    def update(self, order_id: str, payload: OrderUpdate) -> OrderResponse | None:
        model = self.session.get(OrderModel, order_id)
        if model is None:
            return None
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            if value is None:
                continue
            if key == "requested_projects":
                setattr(model, key, _json_dump(value))
            elif hasattr(value, "value"):
                setattr(model, key, value.value)
            else:
                setattr(model, key, value)
        model.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(model)
        return OrderResponse(**order_to_dict(model))

    def cancel(self, order_id: str) -> bool:
        model = self.session.get(OrderModel, order_id)
        if model is None:
            return False
        model.status = QueueStatus.CANCELLED.value
        model.updated_at = utc_now()
        self.session.commit()
        return True


class EquipmentRepository:
    def __init__(self, session: Session):
        self.session = session

    def seed_if_empty(self, equipment: Iterable[dict]) -> None:
        if self.session.scalar(select(EquipmentModel.id).limit(1)):
            return
        for item in equipment:
            self.session.add(
                EquipmentModel(
                    id=item["id"],
                    equipment_type=item["equipment_type"],
                    name=item["name"],
                    capacity=item["capacity"],
                    supported_projects=_json_dump(item["supported_projects"]),
                    status=item.get("status", EquipmentStatus.IDLE.value),
                )
            )
        self.session.commit()

    def list_all(self) -> list[dict]:
        return [
            {
                "id": item.id,
                "equipment_type": item.equipment_type,
                "name": item.name,
                "capacity": item.capacity,
                "supported_projects": _json_list(item.supported_projects),
                "status": EquipmentStatus(item.status),
            }
            for item in self.session.scalars(select(EquipmentModel)).all()
        ]


class DetectionProjectRepository:
    def __init__(self, session: Session):
        self.session = session

    def seed_if_empty(self, projects: Iterable[dict]) -> None:
        if self.session.scalar(select(DetectionProjectModel.id).limit(1)):
            return
        for item in projects:
            self.session.add(DetectionProjectModel(**item))
        self.session.commit()

    def list_all(self) -> list[dict]:
        return [
            {
                "id": item.id,
                "certification_type": CertificationType(item.certification_type),
                "project_type": item.project_type,
                "equipment_type": item.equipment_type,
                "sequence": item.sequence,
                "duration_minutes": item.duration_minutes,
            }
            for item in self.session.scalars(select(DetectionProjectModel)).all()
        ]


class QueueEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, order_id: str, event_type: str, detail: dict) -> None:
        self.session.add(
            QueueEventModel(
                id=new_id("event"),
                order_id=order_id,
                event_type=event_type,
                detail=_json_dump(detail),
            )
        )
        self.session.commit()
