from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain.schemas import EquipmentStatus, QueueStatus, utc_now


class Base(DeclarativeBase):
    pass


class OrderModel(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_type: Mapped[str] = mapped_column(String(20), index=True)
    sample_name: Mapped[str] = mapped_column(String(120))
    sample_quantity: Mapped[int] = mapped_column(Integer)
    certification_type: Mapped[str] = mapped_column(String(40), index=True)
    requested_projects: Mapped[str] = mapped_column(Text, default="[]")
    detection_route: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default=QueueStatus.PENDING.value, index=True)
    arrival_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    promised_finish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class EquipmentModel(Base):
    __tablename__ = "equipment"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    equipment_type: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(120))
    capacity: Mapped[int] = mapped_column(Integer)
    supported_projects: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default=EquipmentStatus.IDLE.value)


class DetectionProjectModel(Base):
    __tablename__ = "detection_projects"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    certification_type: Mapped[str] = mapped_column(String(40), index=True)
    project_type: Mapped[str] = mapped_column(String(80))
    equipment_type: Mapped[str] = mapped_column(String(80))
    sequence: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer)


class QueueEventModel(Base):
    __tablename__ = "queue_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ScheduleRunModel(Base):
    __tablename__ = "schedule_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    scheduled_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ScheduleStepModel(Base):
    __tablename__ = "schedule_steps"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    order_type: Mapped[str] = mapped_column(String(20), index=True)
    sample_name: Mapped[str] = mapped_column(String(120))
    certification_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    project_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    project_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    equipment_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    equipment_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    batch_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_batches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    arrival_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promised_finish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    delay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
