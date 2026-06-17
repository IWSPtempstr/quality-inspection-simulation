from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain.schemas import (
    DatasetReplayStatus,
    EquipmentStatus,
    NotificationStatus,
    NotificationType,
    QueueStatus,
    SchedulingEventStatus,
    utc_now,
)


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
    preprocessing_profile: Mapped[str] = mapped_column(Text, default="{}")
    sample_storage_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
    transfer_requirements: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default=QueueStatus.PENDING.value, index=True)
    arrival_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    promised_finish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parent_order_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    retest_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    lab_area: Mapped[str] = mapped_column(String(80), default="lab")
    setup_minutes: Mapped[int] = mapped_column(Integer, default=0)
    operator_requirements: Mapped[str] = mapped_column(Text, default="{}")
    consumable_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    consumable_units_per_batch: Mapped[int] = mapped_column(Integer, default=0)


class QueueEventModel(Base):
    __tablename__ = "queue_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SchedulingEventModel(Base):
    __tablename__ = "scheduling_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(30), default="medium", index=True)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(80), default="api", index=True)
    status: Mapped[str] = mapped_column(String(30), default=SchedulingEventStatus.PENDING.value, index=True)
    fingerprint: Mapped[str] = mapped_column(String(160), index=True)
    debounce_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


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
    step_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    project_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    equipment_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    equipment_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lab_area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    assigned_employee_ids: Mapped[str] = mapped_column(Text, default="[]")
    resource_ids: Mapped[str] = mapped_column(Text, default="[]")
    constraint_detail: Mapped[str] = mapped_column(Text, default="{}")
    setup_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    staff_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    consumable_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    consumable_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    execution_status: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    locked: Mapped[int] = mapped_column(Integer, default=0, index=True)
    actual_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DatasetReplayRunModel(Base):
    __tablename__ = "dataset_replay_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    dataset_name: Mapped[str] = mapped_column(String(120), index=True)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    imported_orders: Mapped[int] = mapped_column(Integer, default=0)
    current_simulation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    speed_minutes_per_second: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(30), default=DatasetReplayStatus.CREATED.value, index=True)
    latest_order_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    latest_source_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latest_schedule_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class DatasetReplayItemModel(Base):
    __tablename__ = "dataset_replay_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    sequence: Mapped[int] = mapped_column(Integer, index=True)
    original_order_id: Mapped[str] = mapped_column(String(120), index=True)
    arrival_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    import_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    system_order_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_payload: Mapped[str] = mapped_column(Text, default="{}")
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class NotificationModel(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    notification_type: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(30), default=NotificationStatus.PENDING.value, index=True)
    severity: Mapped[str] = mapped_column(String(30), default="info", index=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    step_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    related_resource_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    planned_trigger_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40), index=True)
    permissions: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(80), index=True)
    actor_role: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(80), index=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    detail: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class AgentTraceModel(Base):
    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(80), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="success", index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    visited_agents: Mapped[str] = mapped_column(Text, default="[]")
    handoffs: Mapped[str] = mapped_column(Text, default="[]")
    tool_calls: Mapped[str] = mapped_column(Text, default="[]")
    token_usage: Mapped[str] = mapped_column(Text, default="{}")
    errors: Mapped[str] = mapped_column(Text, default="[]")
    payload_summary: Mapped[str] = mapped_column(Text, default="{}")
    result_summary: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class AgentTraceStepModel(Base):
    __tablename__ = "agent_trace_steps"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(40), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    agent_name: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), default="success", index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[str] = mapped_column(Text, default="[]")
    token_usage: Mapped[str] = mapped_column(Text, default="{}")


class AgentSessionModel(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    summary: Mapped[str] = mapped_column(Text, default="{}")
    last_task_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    last_trace_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
