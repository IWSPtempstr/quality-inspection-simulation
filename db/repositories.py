from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy import delete
from sqlalchemy.orm import Session

from db.models import (
    AgentTraceModel,
    AgentTraceStepModel,
    AuditLogModel,
    DatasetReplayItemModel,
    DatasetReplayRunModel,
    DetectionProjectModel,
    EquipmentModel,
    NotificationModel,
    OrderModel,
    QueueEventModel,
    SchedulingEventModel,
    ScheduleRunModel,
    ScheduleStepModel,
    UserModel,
)
from domain.schemas import (
    AuditLogResponse,
    CertificationType,
    DatasetReplayStatus,
    EquipmentStatus,
    NotificationResponse,
    NotificationStatus,
    NotificationType,
    OrderCreate,
    OrderResponse,
    OrderType,
    OrderUpdate,
    QueueStatus,
    SchedulingEventCreate,
    SchedulingEventResponse,
    SchedulingEventStatus,
    UserResponse,
    new_id,
    utc_now,
)


def _json_dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def _json_value(value: str | None):
    if not value:
        return []
    return json.loads(value)


def _json_dict(value: str | None) -> dict:
    if not value:
        return {}
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def _model_dump_list(value) -> list[dict]:
    return [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in (value or [])
    ]


def _model_dump_dict(value) -> dict:
    if value is None:
        return {}
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def order_to_dict(order: OrderModel) -> dict:
    return {
        "id": order.id,
        "order_type": OrderType(order.order_type),
        "sample_name": order.sample_name,
        "sample_quantity": order.sample_quantity,
        "certification_type": CertificationType(order.certification_type),
        "requested_projects": _json_list(order.requested_projects),
        "detection_route": _json_value(order.detection_route),
        "preprocessing_profile": _json_dict(order.preprocessing_profile) or None,
        "sample_storage_class": order.sample_storage_class,
        "transfer_requirements": _json_dict(order.transfer_requirements),
        "status": QueueStatus(order.status),
        "arrival_time": order.arrival_time,
        "promised_finish_time": order.promised_finish_time,
        "parent_order_id": order.parent_order_id,
        "retest_reason": order.retest_reason,
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
            detection_route=_json_dump(_model_dump_list(payload.detection_route)),
            preprocessing_profile=_json_dump(_model_dump_dict(payload.preprocessing_profile)),
            sample_storage_class=payload.sample_storage_class,
            transfer_requirements=_json_dump(payload.transfer_requirements),
            status=QueueStatus.PENDING.value,
            arrival_time=payload.arrival_time,
            promised_finish_time=payload.promised_finish_time,
            parent_order_id=payload.parent_order_id,
            retest_reason=payload.retest_reason,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return OrderResponse(**order_to_dict(model))

    def list_active(self) -> list[dict]:
        statement = select(OrderModel).where(OrderModel.status != QueueStatus.CANCELLED.value)
        return [order_to_dict(item) for item in self.session.scalars(statement).all()]

    def list(
        self,
        *,
        status: str | None = None,
        order_type: str | None = None,
        certification_type: str | None = None,
        q: str | None = None,
        include_cancelled: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        filters = []
        if not include_cancelled:
            filters.append(OrderModel.status != QueueStatus.CANCELLED.value)
        if status:
            filters.append(OrderModel.status == status)
        if order_type:
            filters.append(OrderModel.order_type == order_type)
        if certification_type:
            filters.append(OrderModel.certification_type == certification_type)
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(
                or_(
                    OrderModel.id.like(pattern),
                    OrderModel.sample_name.like(pattern),
                    OrderModel.requested_projects.like(pattern),
                    OrderModel.detection_route.like(pattern),
                )
            )

        statement = select(OrderModel)
        count_statement = select(func.count()).select_from(OrderModel)
        if filters:
            statement = statement.where(*filters)
            count_statement = count_statement.where(*filters)
        statement = statement.order_by(OrderModel.created_at.desc()).limit(limit).offset(offset)
        return {
            "items": [order_to_dict(item) for item in self.session.scalars(statement).all()],
            "total": self.session.scalar(count_statement) or 0,
            "limit": limit,
            "offset": offset,
        }

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
            elif key == "detection_route":
                setattr(model, key, _json_dump(_model_dump_list(value)))
            elif key == "preprocessing_profile":
                setattr(model, key, _json_dump(_model_dump_dict(value)))
            elif key == "transfer_requirements":
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

    def create_retest(self, original: OrderResponse, reason: str, requested_projects: list[str] | None = None, promised_finish_time=None) -> OrderResponse:
        payload = OrderCreate(
            order_type=original.order_type,
            sample_name=f"{original.sample_name}-复检",
            sample_quantity=original.sample_quantity,
            certification_type=original.certification_type,
            requested_projects=requested_projects if requested_projects is not None else original.requested_projects,
            detection_route=original.detection_route,
            preprocessing_profile=original.preprocessing_profile,
            sample_storage_class=original.sample_storage_class,
            transfer_requirements=original.transfer_requirements,
            arrival_time=utc_now(),
            promised_finish_time=promised_finish_time or original.promised_finish_time,
            parent_order_id=original.id,
            retest_reason=reason,
        )
        return self.create(payload)

    def set_status(self, order_id: str, status: QueueStatus) -> OrderResponse | None:
        model = self.session.get(OrderModel, order_id)
        if model is None:
            return None
        model.status = status.value
        model.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(model)
        return OrderResponse(**order_to_dict(model))


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
            self.session.add(
                DetectionProjectModel(
                    id=item["id"],
                    certification_type=item["certification_type"],
                    project_type=item["project_type"],
                    equipment_type=item["equipment_type"],
                    sequence=item["sequence"],
                    duration_minutes=item["duration_minutes"],
                    lab_area=item.get("lab_area", "lab"),
                    setup_minutes=item.get("setup_minutes", 0),
                    operator_requirements=_json_dump(item.get("operator_requirements", {})),
                    consumable_type=item.get("consumable_type"),
                    consumable_units_per_batch=item.get("consumable_units_per_batch", 0),
                )
            )
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
                "lab_area": item.lab_area,
                "setup_minutes": item.setup_minutes,
                "operator_requirements": _json_dict(item.operator_requirements),
                "consumable_type": item.consumable_type,
                "consumable_units_per_batch": item.consumable_units_per_batch,
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


class SchedulingEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        payload: SchedulingEventCreate,
        fingerprint: str,
        debounce_until: datetime,
        status: SchedulingEventStatus = SchedulingEventStatus.PENDING,
        processed_at: datetime | None = None,
        schedule_run_id: str | None = None,
        error_message: str | None = None,
    ) -> dict:
        model = SchedulingEventModel(
            id=new_id("sched-event"),
            event_type=payload.event_type,
            severity=payload.severity,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            payload=_json_dump(payload.payload),
            source=payload.source,
            status=status.value,
            fingerprint=fingerprint,
            debounce_until=debounce_until,
            processed_at=processed_at,
            schedule_run_id=schedule_run_id,
            error_message=error_message,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._to_dict(model)

    def list(
        self,
        status: str | SchedulingEventStatus | None = None,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> list[dict]:
        statement = select(SchedulingEventModel).order_by(SchedulingEventModel.created_at.asc())
        if status:
            statement = statement.where(SchedulingEventModel.status == self._enum_value(status))
        if event_type:
            statement = statement.where(SchedulingEventModel.event_type == event_type)
        if entity_type:
            statement = statement.where(SchedulingEventModel.entity_type == entity_type)
        if entity_id:
            statement = statement.where(SchedulingEventModel.entity_id == entity_id)
        return [self._to_dict(item) for item in self.session.scalars(statement).all()]

    def count_pending(self) -> int:
        return len(self.list(status=SchedulingEventStatus.PENDING))

    def find_active_duplicate(self, fingerprint: str, now: datetime) -> dict | None:
        model = self.session.scalars(
            select(SchedulingEventModel)
            .where(SchedulingEventModel.fingerprint == fingerprint)
            .where(SchedulingEventModel.debounce_until >= now)
            .order_by(SchedulingEventModel.created_at.desc())
        ).first()
        return self._to_dict(model) if model else None

    def pending_due(self, now: datetime) -> list[dict]:
        models = self.session.scalars(
            select(SchedulingEventModel)
            .where(SchedulingEventModel.status == SchedulingEventStatus.PENDING.value)
            .where(SchedulingEventModel.created_at <= now)
            .order_by(SchedulingEventModel.created_at.asc())
        ).all()
        return [self._to_dict(model) for model in models]

    def mark_processing(self, event_ids: list[str], now: datetime) -> None:
        if not event_ids:
            return
        for event_id in event_ids:
            model = self.session.get(SchedulingEventModel, event_id)
            if model is not None and model.status == SchedulingEventStatus.PENDING.value:
                model.status = SchedulingEventStatus.PROCESSING.value
                model.updated_at = now
        self.session.commit()

    def mark_done(self, event_ids: list[str], schedule_run_id: str, now: datetime) -> None:
        self._mark_many(
            event_ids=event_ids,
            status=SchedulingEventStatus.DONE,
            now=now,
            schedule_run_id=schedule_run_id,
        )

    def mark_failed(self, event_ids: list[str], error_message: str, now: datetime) -> None:
        self._mark_many(
            event_ids=event_ids,
            status=SchedulingEventStatus.FAILED,
            now=now,
            error_message=error_message,
        )

    def resolve(self, event_id: str, status: SchedulingEventStatus, now: datetime, resolution_note: str | None = None) -> dict | None:
        model = self.session.get(SchedulingEventModel, event_id)
        if model is None:
            return None
        model.status = status.value
        model.processed_at = now
        model.updated_at = now
        payload = _json_dict(model.payload)
        if resolution_note:
            payload["resolution_note"] = resolution_note
            model.payload = _json_dump(payload)
        return_value = self._to_dict(model)
        self.session.commit()
        return return_value

    def _mark_many(
        self,
        event_ids: list[str],
        status: SchedulingEventStatus,
        now: datetime,
        schedule_run_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        for event_id in event_ids:
            model = self.session.get(SchedulingEventModel, event_id)
            if model is None:
                continue
            model.status = status.value
            model.processed_at = now
            model.updated_at = now
            if schedule_run_id is not None:
                model.schedule_run_id = schedule_run_id
            if error_message is not None:
                model.error_message = error_message
        self.session.commit()

    def _to_dict(self, model: SchedulingEventModel) -> dict:
        return SchedulingEventResponse(
            id=model.id,
            event_type=model.event_type,
            severity=model.severity,
            entity_type=model.entity_type,
            entity_id=model.entity_id,
            payload=_json_dict(model.payload),
            source=model.source,
            status=SchedulingEventStatus(model.status),
            fingerprint=model.fingerprint,
            debounce_until=model.debounce_until,
            processed_at=model.processed_at,
            schedule_run_id=model.schedule_run_id,
            error_message=model.error_message,
            created_at=model.created_at,
            updated_at=model.updated_at,
        ).model_dump(mode="json")

    def _enum_value(self, value):
        return value.value if hasattr(value, "value") else value


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
                    execution_status=self._enum_value(order["status"]),
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
                        execution_status=step.get("execution_status") or QueueStatus.SCHEDULED.value,
                        locked=1 if step.get("locked") else 0,
                        actual_start_time=self._parse_datetime(step.get("actual_start_time")),
                        actual_end_time=self._parse_datetime(step.get("actual_end_time")),
                        execution_note=step.get("execution_note"),
                        step_kind=step.get("step_kind"),
                        project_id=step.get("project_id"),
                        project_type=step.get("project_type"),
                        equipment_type=step.get("equipment_type"),
                        equipment_id=step.get("equipment_id"),
                        lab_area=step.get("lab_area"),
                        assigned_employee_ids=_json_dump(step.get("assigned_employee_ids", [])),
                        resource_ids=_json_dump(step.get("resource_ids", [])),
                        constraint_detail=_json_dump(step.get("constraint_detail", {})),
                        setup_minutes=step.get("setup_minutes"),
                        staff_role=step.get("staff_role"),
                        consumable_type=step.get("consumable_type"),
                        consumable_units=step.get("consumable_units"),
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
                    execution_status=QueueStatus.BLOCKED.value,
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
            "step_kind": step.step_kind,
            "project_id": step.project_id,
            "project_type": step.project_type,
            "equipment_type": step.equipment_type,
            "equipment_id": step.equipment_id,
            "lab_area": step.lab_area,
            "assigned_employee_ids": _json_value(step.assigned_employee_ids),
            "resource_ids": _json_value(step.resource_ids),
            "constraint_detail": _json_dict(step.constraint_detail),
            "setup_minutes": step.setup_minutes,
            "staff_role": step.staff_role,
            "consumable_type": step.consumable_type,
            "consumable_units": step.consumable_units,
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
            "execution_status": step.execution_status,
            "locked": bool(step.locked),
            "actual_start_time": step.actual_start_time,
            "actual_end_time": step.actual_end_time,
            "execution_note": step.execution_note,
        }

    def _enum_value(self, value):
        return value.value if hasattr(value, "value") else value

    def _parse_datetime(self, value):
        if not value:
            return None
        if hasattr(value, "isoformat"):
            return value
        return datetime.fromisoformat(value)

    def mark_step_running(self, step_id: str, actual_time: datetime, note: str | None = None) -> dict | None:
        step = self.session.get(ScheduleStepModel, step_id)
        if step is None or not step.step_kind:
            return None
        step.execution_status = QueueStatus.RUNNING.value
        step.status = QueueStatus.RUNNING.value
        step.locked = 1
        step.actual_start_time = actual_time
        step.execution_note = note
        order = self.session.get(OrderModel, step.order_id)
        if order is not None:
            order.status = QueueStatus.RUNNING.value
            order.updated_at = actual_time
        for row in self.session.scalars(
            select(ScheduleStepModel)
            .where(ScheduleStepModel.run_id == step.run_id)
            .where(ScheduleStepModel.order_id == step.order_id)
            .where(ScheduleStepModel.step_kind.is_(None))
        ).all():
            row.status = QueueStatus.RUNNING.value
            row.execution_status = QueueStatus.RUNNING.value
        self.session.commit()
        self.session.refresh(step)
        return self._step_to_dict(step)

    def mark_step_completed(self, step_id: str, actual_time: datetime, note: str | None = None) -> dict | None:
        step = self.session.get(ScheduleStepModel, step_id)
        if step is None or not step.step_kind:
            return None
        step.execution_status = QueueStatus.COMPLETED.value
        step.status = QueueStatus.COMPLETED.value
        step.locked = 0
        step.actual_end_time = actual_time
        step.execution_note = note
        order_steps = self.session.scalars(
            select(ScheduleStepModel)
            .where(ScheduleStepModel.run_id == step.run_id)
            .where(ScheduleStepModel.order_id == step.order_id)
            .where(ScheduleStepModel.step_kind.is_not(None))
        ).all()
        order_complete = all(
            item.id == step.id or item.execution_status == QueueStatus.COMPLETED.value
            for item in order_steps
        )
        order = self.session.get(OrderModel, step.order_id)
        if order is not None:
            order.status = QueueStatus.COMPLETED.value if order_complete else QueueStatus.RUNNING.value
            order.updated_at = actual_time
        order_status = QueueStatus.COMPLETED.value if order_complete else QueueStatus.RUNNING.value
        for row in self.session.scalars(
            select(ScheduleStepModel)
            .where(ScheduleStepModel.run_id == step.run_id)
            .where(ScheduleStepModel.order_id == step.order_id)
            .where(ScheduleStepModel.step_kind.is_(None))
        ).all():
            row.status = order_status
            row.execution_status = order_status
        self.session.commit()
        self.session.refresh(step)
        return self._step_to_dict(step)


class RuntimeRepository:
    def __init__(self, session: Session):
        self.session = session

    def clear_runtime(self, include_replay: bool = True) -> None:
        for model in [
            NotificationModel,
            SchedulingEventModel,
            QueueEventModel,
            ScheduleStepModel,
            ScheduleRunModel,
            OrderModel,
        ]:
            self.session.execute(delete(model))
        if include_replay:
            self.session.execute(delete(DatasetReplayItemModel))
            self.session.execute(delete(DatasetReplayRunModel))
        self.session.commit()


class DatasetReplayRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_run(
        self,
        *,
        dataset_name: str,
        total_orders: int,
        start_time: datetime,
        end_time: datetime,
        speed_minutes_per_second: int,
    ) -> dict:
        model = DatasetReplayRunModel(
            id=new_id("replay"),
            dataset_name=dataset_name,
            total_orders=total_orders,
            imported_orders=0,
            current_simulation_time=start_time,
            start_time=start_time,
            end_time=end_time,
            speed_minutes_per_second=speed_minutes_per_second,
            status=DatasetReplayStatus.CREATED.value,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._run_to_dict(model)

    def create_items(self, run_id: str, orders: list[dict]) -> None:
        for index, order in enumerate(orders, start=1):
            self.session.add(
                DatasetReplayItemModel(
                    id=new_id("replay-item"),
                    run_id=run_id,
                    sequence=index,
                    original_order_id=str(order.get("order_id") or f"dataset-order-{index:05d}"),
                    arrival_time=self._parse_datetime(order["arrival_time"]),
                    original_payload=_json_dump(order),
                )
            )
        self.session.commit()

    def get_run(self, run_id: str) -> dict | None:
        model = self.session.get(DatasetReplayRunModel, run_id)
        return self._run_to_dict(model) if model else None

    def get_run_with_items(self, run_id: str, limit: int = 50) -> dict | None:
        run = self.session.get(DatasetReplayRunModel, run_id)
        if run is None:
            return None
        items = self.session.scalars(
            select(DatasetReplayItemModel)
            .where(DatasetReplayItemModel.run_id == run_id)
            .order_by(DatasetReplayItemModel.sequence.asc())
            .limit(limit)
        ).all()
        return {
            **self._run_to_dict(run),
            "items": [self._item_to_dict(item) for item in items],
        }

    def latest_run(self) -> dict | None:
        model = self.session.scalars(
            select(DatasetReplayRunModel).order_by(DatasetReplayRunModel.created_at.desc())
        ).first()
        return self._run_to_dict(model) if model else None

    def due_items(self, run_id: str, current_time: datetime) -> list[dict]:
        items = self.session.scalars(
            select(DatasetReplayItemModel)
            .where(DatasetReplayItemModel.run_id == run_id)
            .where(DatasetReplayItemModel.import_status == "pending")
            .where(DatasetReplayItemModel.arrival_time <= current_time)
            .order_by(DatasetReplayItemModel.arrival_time.asc(), DatasetReplayItemModel.sequence.asc())
        ).all()
        return [self._item_to_dict(item) for item in items]

    def next_pending_item(self, run_id: str) -> dict | None:
        model = self.session.scalars(
            select(DatasetReplayItemModel)
            .where(DatasetReplayItemModel.run_id == run_id)
            .where(DatasetReplayItemModel.import_status == "pending")
            .order_by(DatasetReplayItemModel.arrival_time.asc(), DatasetReplayItemModel.sequence.asc())
        ).first()
        return self._item_to_dict(model) if model else None

    def mark_item_imported(self, item_id: str, system_order_id: str, imported_at: datetime) -> dict | None:
        model = self.session.get(DatasetReplayItemModel, item_id)
        if model is None:
            return None
        model.import_status = "imported"
        model.system_order_id = system_order_id
        model.imported_at = imported_at
        model.updated_at = imported_at
        self.session.commit()
        self.session.refresh(model)
        return self._item_to_dict(model)

    def mark_item_failed(self, item_id: str, error_message: str, failed_at: datetime) -> dict | None:
        model = self.session.get(DatasetReplayItemModel, item_id)
        if model is None:
            return None
        model.import_status = "failed"
        model.error_message = error_message
        model.updated_at = failed_at
        self.session.commit()
        self.session.refresh(model)
        return self._item_to_dict(model)

    def imported_count(self, run_id: str) -> int:
        return self.session.scalar(
            select(func.count())
            .select_from(DatasetReplayItemModel)
            .where(DatasetReplayItemModel.run_id == run_id)
            .where(DatasetReplayItemModel.import_status == "imported")
        ) or 0

    def update_run(
        self,
        run_id: str,
        *,
        status: DatasetReplayStatus | str | None = None,
        current_simulation_time: datetime | None = None,
        imported_orders: int | None = None,
        latest_order_id: str | None = None,
        latest_source_order_id: str | None = None,
        latest_schedule_run_id: str | None = None,
        error_message: str | None = None,
    ) -> dict | None:
        model = self.session.get(DatasetReplayRunModel, run_id)
        if model is None:
            return None
        if status is not None:
            model.status = self._enum_value(status)
        if current_simulation_time is not None:
            model.current_simulation_time = current_simulation_time
        if imported_orders is not None:
            model.imported_orders = imported_orders
        if latest_order_id is not None:
            model.latest_order_id = latest_order_id
        if latest_source_order_id is not None:
            model.latest_source_order_id = latest_source_order_id
        if latest_schedule_run_id is not None:
            model.latest_schedule_run_id = latest_schedule_run_id
        if error_message is not None:
            model.error_message = error_message
        model.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(model)
        return self._run_to_dict(model)

    def _run_to_dict(self, model: DatasetReplayRunModel) -> dict:
        return {
            "id": model.id,
            "dataset_name": model.dataset_name,
            "total_orders": model.total_orders,
            "imported_orders": model.imported_orders,
            "current_simulation_time": model.current_simulation_time,
            "start_time": model.start_time,
            "end_time": model.end_time,
            "speed_minutes_per_second": model.speed_minutes_per_second,
            "status": model.status,
            "latest_order_id": model.latest_order_id,
            "latest_source_order_id": model.latest_source_order_id,
            "latest_schedule_run_id": model.latest_schedule_run_id,
            "error_message": model.error_message,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }

    def _item_to_dict(self, model: DatasetReplayItemModel) -> dict:
        return {
            "id": model.id,
            "run_id": model.run_id,
            "sequence": model.sequence,
            "original_order_id": model.original_order_id,
            "arrival_time": model.arrival_time,
            "import_status": model.import_status,
            "system_order_id": model.system_order_id,
            "error_message": model.error_message,
            "original_payload": _json_dict(model.original_payload),
            "imported_at": model.imported_at,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }

    def _parse_datetime(self, value):
        if hasattr(value, "isoformat"):
            return value
        return datetime.fromisoformat(value)

    def _enum_value(self, value):
        return value.value if hasattr(value, "value") else value


class NotificationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_many(self, notifications: Iterable[dict]) -> list[dict]:
        models = []
        for item in notifications:
            model = NotificationModel(
                id=item.get("id") or new_id("notification"),
                notification_type=self._enum_value(item["notification_type"]),
                status=self._enum_value(item.get("status", NotificationStatus.PENDING)),
                severity=item.get("severity", "info"),
                title=item["title"],
                message=item["message"],
                order_id=item.get("order_id"),
                run_id=item.get("run_id"),
                step_position=item.get("step_position"),
                related_resource_id=item.get("related_resource_id"),
                planned_trigger_time=self._parse_datetime(item["planned_trigger_time"]),
                triggered_at=self._parse_datetime(item.get("triggered_at")) if item.get("triggered_at") else None,
                read_at=self._parse_datetime(item.get("read_at")) if item.get("read_at") else None,
                payload=_json_dump(item.get("payload", {})),
            )
            self.session.add(model)
            models.append(model)
        self.session.commit()
        for model in models:
            self.session.refresh(model)
        return [self._to_dict(model) for model in models]

    def list(
        self,
        status: str | NotificationStatus | None = None,
        notification_type: str | NotificationType | None = None,
    ) -> list[dict]:
        statement = select(NotificationModel).order_by(NotificationModel.planned_trigger_time.asc(), NotificationModel.created_at.asc())
        if status:
            statement = statement.where(NotificationModel.status == self._enum_value(status))
        if notification_type:
            statement = statement.where(NotificationModel.notification_type == self._enum_value(notification_type))
        return [self._to_dict(item) for item in self.session.scalars(statement).all()]

    def list_due(self, current_time: datetime) -> list[dict]:
        statement = (
            select(NotificationModel)
            .where(NotificationModel.status == NotificationStatus.PENDING.value)
            .where(NotificationModel.planned_trigger_time <= current_time)
            .order_by(NotificationModel.planned_trigger_time.asc(), NotificationModel.created_at.asc())
        )
        return [self._to_dict(item) for item in self.session.scalars(statement).all()]

    def trigger_due(self, current_time: datetime) -> list[dict]:
        models = self.session.scalars(
            select(NotificationModel)
            .where(NotificationModel.status == NotificationStatus.PENDING.value)
            .where(NotificationModel.planned_trigger_time <= current_time)
            .order_by(NotificationModel.planned_trigger_time.asc(), NotificationModel.created_at.asc())
        ).all()
        for model in models:
            model.status = NotificationStatus.TRIGGERED.value
            model.triggered_at = current_time
            model.updated_at = current_time
        self.session.commit()
        return [self._to_dict(model) for model in models]

    def mark_read(self, notification_id: str, read_at: datetime) -> dict | None:
        model = self.session.get(NotificationModel, notification_id)
        if model is None:
            return None
        model.status = NotificationStatus.READ.value
        model.read_at = read_at
        model.updated_at = read_at
        self.session.commit()
        self.session.refresh(model)
        return self._to_dict(model)

    def _to_dict(self, model: NotificationModel) -> dict:
        return {
            "id": model.id,
            "notification_type": NotificationType(model.notification_type),
            "status": NotificationStatus(model.status),
            "severity": model.severity,
            "title": model.title,
            "message": model.message,
            "order_id": model.order_id,
            "run_id": model.run_id,
            "step_position": model.step_position,
            "related_resource_id": model.related_resource_id,
            "planned_trigger_time": model.planned_trigger_time,
            "triggered_at": model.triggered_at,
            "read_at": model.read_at,
            "payload": _json_dict(model.payload),
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }

    def _enum_value(self, value):
        return value.value if hasattr(value, "value") else value

    def _parse_datetime(self, value):
        if hasattr(value, "isoformat"):
            return value
        return datetime.fromisoformat(value)


class UserRepository:
    DEFAULT_USERS = [
        {
            "id": "admin",
            "name": "系统管理员",
            "role": "admin",
            "permissions": ["*"],
        },
        {
            "id": "scheduler",
            "name": "排程员",
            "role": "scheduler",
            "permissions": ["orders:write", "schedule:write", "events:resolve"],
        },
        {
            "id": "operator",
            "name": "检测员",
            "role": "operator",
            "permissions": ["execution:write", "notifications:read"],
        },
    ]

    def __init__(self, session: Session):
        self.session = session

    def seed_if_empty(self) -> None:
        if self.session.scalar(select(UserModel.id).limit(1)):
            return
        for item in self.DEFAULT_USERS:
            self.session.add(
                UserModel(
                    id=item["id"],
                    name=item["name"],
                    role=item["role"],
                    permissions=_json_dump(item["permissions"]),
                    active=1,
                )
            )
        self.session.commit()

    def list_all(self) -> list[dict]:
        return [self._to_dict(item) for item in self.session.scalars(select(UserModel)).all()]

    def get(self, user_id: str) -> dict | None:
        model = self.session.get(UserModel, user_id)
        return self._to_dict(model) if model else None

    def _to_dict(self, model: UserModel) -> dict:
        return UserResponse(
            id=model.id,
            name=model.name,
            role=model.role,
            permissions=_json_list(model.permissions),
            active=bool(model.active),
            created_at=model.created_at,
            updated_at=model.updated_at,
        ).model_dump(mode="json")


class AuditLogRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(
        self,
        actor_id: str,
        actor_role: str,
        action: str,
        target_type: str,
        target_id: str | None = None,
        detail: dict | None = None,
    ) -> dict:
        model = AuditLogModel(
            id=new_id("audit"),
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=_json_dump(detail or {}),
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._to_dict(model)

    def list(self, action: str | None = None, target_type: str | None = None, target_id: str | None = None) -> list[dict]:
        statement = select(AuditLogModel).order_by(AuditLogModel.created_at.desc())
        if action:
            statement = statement.where(AuditLogModel.action == action)
        if target_type:
            statement = statement.where(AuditLogModel.target_type == target_type)
        if target_id:
            statement = statement.where(AuditLogModel.target_id == target_id)
        return [self._to_dict(item) for item in self.session.scalars(statement).all()]

    def _to_dict(self, model: AuditLogModel) -> dict:
        return AuditLogResponse(
            id=model.id,
            actor_id=model.actor_id,
            actor_role=model.actor_role,
            action=model.action,
            target_type=model.target_type,
            target_id=model.target_id,
            detail=_json_dict(model.detail),
            created_at=model.created_at,
        ).model_dump(mode="json")


class AgentTraceRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_trace(
        self,
        *,
        trace: dict,
        task_type: str,
        actor_id: str | None = None,
        actor_role: str | None = None,
        payload_summary: dict | None = None,
        result_summary: dict | None = None,
    ) -> dict:
        trace_id = trace["trace_id"]
        errors = trace.get("errors", [])
        model = AgentTraceModel(
            id=trace_id,
            task_type=task_type,
            actor_id=actor_id,
            actor_role=actor_role,
            status="failed" if errors else "success",
            latency_ms=int(trace.get("latency_ms") or 0),
            visited_agents=_json_dump(trace.get("visited_agents", [])),
            handoffs=_json_dump(trace.get("handoffs", [])),
            tool_calls=_json_dump(trace.get("tool_calls", [])),
            token_usage=_json_dump(trace.get("token_usage", {})),
            errors=_json_dump(errors),
            payload_summary=_json_dump(payload_summary or {}),
            result_summary=_json_dump(result_summary or {}),
            created_at=self._parse_datetime(trace.get("started_at")) or utc_now(),
        )
        self.session.add(model)
        for index, step in enumerate(trace.get("steps", []), start=1):
            self.session.add(
                AgentTraceStepModel(
                    id=new_id("trace-step"),
                    trace_id=trace_id,
                    sequence=index,
                    agent_name=step.get("agent_name", "unknown"),
                    status=step.get("status", "success"),
                    latency_ms=int(step.get("latency_ms") or 0),
                    started_at=self._parse_datetime(step.get("started_at")) or utc_now(),
                    ended_at=self._parse_datetime(step.get("ended_at")) or utc_now(),
                    error_message=step.get("error"),
                    tool_calls=_json_dump(step.get("tool_calls", [])),
                    token_usage=_json_dump(step.get("token_usage", {})),
                )
            )
        self.session.commit()
        return self.get_trace(trace_id) or {}

    def list_traces(
        self,
        *,
        task_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        filters = []
        if task_type:
            filters.append(AgentTraceModel.task_type == task_type)
        if status:
            filters.append(AgentTraceModel.status == status)
        statement = select(AgentTraceModel)
        count_statement = select(func.count()).select_from(AgentTraceModel)
        if filters:
            statement = statement.where(*filters)
            count_statement = count_statement.where(*filters)
        statement = statement.order_by(AgentTraceModel.created_at.desc()).limit(limit).offset(offset)
        models = self.session.scalars(statement).all()
        return {
            "items": [self._trace_to_summary(model) for model in models],
            "total": self.session.scalar(count_statement) or 0,
            "limit": limit,
            "offset": offset,
        }

    def get_trace(self, trace_id: str) -> dict | None:
        model = self.session.get(AgentTraceModel, trace_id)
        if model is None:
            return None
        steps = self.session.scalars(
            select(AgentTraceStepModel)
            .where(AgentTraceStepModel.trace_id == trace_id)
            .order_by(AgentTraceStepModel.sequence.asc())
        ).all()
        return {
            **self._trace_to_summary(model),
            "steps": [self._step_to_dict(step) for step in steps],
            "payload_summary": _json_dict(model.payload_summary),
            "result_summary": _json_dict(model.result_summary),
        }

    def threshold_status(self) -> dict:
        traces = self.session.scalars(select(AgentTraceModel)).all()
        total = len(traces)
        successes = sum(1 for item in traces if item.status == "success")
        success_rate = successes / total if total else 1.0
        latency_values = sorted(int(item.latency_ms or 0) for item in traces)
        p95_index = max(0, int(len(latency_values) * 0.95) - 1) if latency_values else 0
        p95_latency = latency_values[p95_index] if latency_values else 0
        thresholds = {
            "agent_success_rate_min": 0.95,
            "trajectory_compliance_rate_min": 0.95,
            "mcp_tool_success_rate_min": 0.98,
            "rag_hit_at_3_min": 0.8,
            "queue_scheduler_500_orders_latency_ms_max": 10000,
            "constraint_violation_count_max": 0,
            "llm_fallback_consecutive_max": 3,
        }
        metrics = {
            "agent_success_rate": round(success_rate, 4),
            "trace_latency_p95_ms": p95_latency,
            "trajectory_compliance_rate": round(success_rate, 4),
        }
        alerts = []
        if success_rate < thresholds["agent_success_rate_min"]:
            alerts.append(
                {
                    "metric": "agent_success_rate",
                    "severity": "warning",
                    "message": "Agent 运行成功率低于阈值",
                }
            )
        return {
            "trace_count": total,
            "metrics": metrics,
            "thresholds": thresholds,
            "alerts": alerts,
        }

    def _trace_to_summary(self, model: AgentTraceModel) -> dict:
        return {
            "trace_id": model.id,
            "task_type": model.task_type,
            "actor_id": model.actor_id,
            "actor_role": model.actor_role,
            "status": model.status,
            "latency_ms": model.latency_ms,
            "visited_agents": _json_value(model.visited_agents),
            "handoffs": _json_value(model.handoffs),
            "tool_calls": _json_value(model.tool_calls),
            "token_usage": _json_dict(model.token_usage),
            "errors": _json_value(model.errors),
            "created_at": model.created_at,
        }

    def _step_to_dict(self, step: AgentTraceStepModel) -> dict:
        return {
            "id": step.id,
            "trace_id": step.trace_id,
            "sequence": step.sequence,
            "agent_name": step.agent_name,
            "status": step.status,
            "latency_ms": step.latency_ms,
            "started_at": step.started_at,
            "ended_at": step.ended_at,
            "error": step.error_message,
            "tool_calls": _json_value(step.tool_calls),
            "token_usage": _json_dict(step.token_usage),
        }

    def _parse_datetime(self, value):
        if not value:
            return None
        if hasattr(value, "isoformat"):
            return value
        return datetime.fromisoformat(value)
