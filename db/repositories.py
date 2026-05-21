from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    DetectionProjectModel,
    EquipmentModel,
    OrderModel,
    QueueEventModel,
    ScheduleRunModel,
    ScheduleStepModel,
)
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
        "arrival_time": order.arrival_time,
        "promised_finish_time": order.promised_finish_time,
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
            arrival_time=payload.arrival_time,
            promised_finish_time=payload.promised_finish_time,
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


class ScheduleRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_from_schedule(self, schedule: dict) -> dict:
        run_id = new_id("schedule")
        scheduled_orders = schedule.get("scheduled_orders", [])
        blocked_orders = schedule.get("blocked_orders", [])
        position = 0
        self.session.add(
                ScheduleRunModel(
                    id=run_id,
                    scheduled_count=len(scheduled_orders),
                    blocked_count=len(blocked_orders),
                    metrics=_json_dump(schedule.get("metrics", {})),
                )
        )
        for order in scheduled_orders:
            self.session.add(
                ScheduleStepModel(
                    id=new_id("step"),
                    run_id=run_id,
                    position=position,
                    order_id=order["id"],
                    order_type=self._enum_value(order["order_type"]),
                    sample_name=order["sample_name"],
                    certification_type=self._enum_value(order["certification_type"]),
                    status=self._enum_value(order["status"]),
                    arrival_time=self._parse_datetime(order.get("arrival_time")),
                    promised_finish_time=self._parse_datetime(order.get("promised_finish_time")),
                    sla_status=order.get("sla_status"),
                    delay_minutes=order.get("delay_minutes"),
                )
            )
            position += 1
            for step in order.get("steps", []):
                self.session.add(
                    ScheduleStepModel(
                        id=new_id("step"),
                        run_id=run_id,
                        position=position,
                        order_id=order["id"],
                        order_type=self._enum_value(order["order_type"]),
                        sample_name=order["sample_name"],
                        certification_type=self._enum_value(order["certification_type"]),
                        status=self._enum_value(order["status"]),
                        project_id=step.get("project_id"),
                        project_type=step.get("project_type"),
                        equipment_type=step.get("equipment_type"),
                        equipment_id=step.get("equipment_id"),
                        sequence=step.get("sequence"),
                        start_minute=step.get("start_minute"),
                        start_time=self._parse_datetime(step.get("start_time")),
                        duration_minutes=step.get("duration_minutes"),
                        end_minute=step.get("end_minute"),
                        end_time=self._parse_datetime(step.get("end_time")),
                        batch_count=step.get("batch_count"),
                        required_batches=step.get("required_batches"),
                        arrival_time=self._parse_datetime(order.get("arrival_time")),
                        promised_finish_time=self._parse_datetime(order.get("promised_finish_time")),
                        sla_status=order.get("sla_status"),
                        delay_minutes=order.get("delay_minutes"),
                    )
                )
                position += 1
        for order in blocked_orders:
            self.session.add(
                ScheduleStepModel(
                    id=new_id("step"),
                    run_id=run_id,
                    position=position,
                    order_id=order["id"],
                    order_type=self._enum_value(order["order_type"]),
                    sample_name=order["sample_name"],
                    certification_type=self._enum_value(order["certification_type"]),
                    status=self._enum_value(order["status"]),
                    blocked_reason=order.get("reason"),
                    arrival_time=self._parse_datetime(order.get("arrival_time")),
                    promised_finish_time=self._parse_datetime(order.get("promised_finish_time")),
                )
            )
            position += 1
        self.session.commit()
        return self.get(run_id)

    def list_runs(self) -> list[dict]:
        runs = self.session.scalars(select(ScheduleRunModel).order_by(ScheduleRunModel.created_at.desc())).all()
        return [self._run_to_dict(run) for run in runs]

    def latest(self) -> dict | None:
        run = self.session.scalars(select(ScheduleRunModel).order_by(ScheduleRunModel.created_at.desc())).first()
        return self._run_to_dict(run) if run else None

    def get(self, run_id: str) -> dict | None:
        run = self.session.get(ScheduleRunModel, run_id)
        if run is None:
            return None
        steps = self.session.scalars(
            select(ScheduleStepModel)
            .where(ScheduleStepModel.run_id == run_id)
            .order_by(ScheduleStepModel.position.asc())
        ).all()
        return {
            **self._run_to_dict(run),
            "steps": [self._step_to_dict(step) for step in steps],
        }

    def _run_to_dict(self, run: ScheduleRunModel) -> dict:
        return {
            "id": run.id,
            "scheduled_count": run.scheduled_count,
            "blocked_count": run.blocked_count,
            "created_at": run.created_at,
            "metrics": json.loads(run.metrics or "{}"),
        }

    def _step_to_dict(self, step: ScheduleStepModel) -> dict:
        return {
            "id": step.id,
            "run_id": step.run_id,
            "position": step.position,
            "order_id": step.order_id,
            "order_type": step.order_type,
            "sample_name": step.sample_name,
            "certification_type": step.certification_type,
            "status": step.status,
            "project_id": step.project_id,
            "project_type": step.project_type,
            "equipment_type": step.equipment_type,
            "equipment_id": step.equipment_id,
            "sequence": step.sequence,
            "start_minute": step.start_minute,
            "start_time": step.start_time,
            "duration_minutes": step.duration_minutes,
            "end_minute": step.end_minute,
            "end_time": step.end_time,
            "batch_count": step.batch_count,
            "required_batches": step.required_batches,
            "arrival_time": step.arrival_time,
            "promised_finish_time": step.promised_finish_time,
            "sla_status": step.sla_status,
            "delay_minutes": step.delay_minutes,
            "blocked_reason": step.blocked_reason,
        }

    def _enum_value(self, value):
        return value.value if hasattr(value, "value") else value

    def _parse_datetime(self, value):
        if not value:
            return None
        if hasattr(value, "isoformat"):
            return value
        return datetime.fromisoformat(value)
