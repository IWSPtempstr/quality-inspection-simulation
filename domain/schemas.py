from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderType(str, Enum):
    NORMAL = "normal"
    URGENT = "urgent"
    VIP = "vip"


class CertificationType(str, Enum):
    CCC = "ccc"
    CVC = "cvc"
    INTERNATIONAL = "international"


class QueueStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class EquipmentStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


class SupervisionMode(str, Enum):
    EXCLUSIVE = "exclusive"
    SHARED_SUPERVISION = "shared_supervision"
    SETUP_ONLY = "setup_only"


class StaffPhase(str, Enum):
    SETUP = "setup"
    RUNNING = "running"
    FULL = "full"
    UNLOAD = "unload"
    SETUP_UNLOAD = "setup_unload"


class StepKind(str, Enum):
    PREPROCESSING = "preprocessing"
    SETUP = "setup"
    DETECTION = "detection"
    TRANSFER = "transfer"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    TRIGGERED = "triggered"
    READ = "read"


class SchedulingEventStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    IGNORED = "ignored"
    FAILED = "failed"


class DatasetReplayStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NotificationType(str, Enum):
    EQUIPMENT_IDLE = "equipment_idle"
    DETECTION_COMPLETED = "detection_completed"
    SAMPLE_PREPROCESSING_TODO = "sample_preprocessing_todo"
    SAMPLE_TRANSFER_REQUIRED = "sample_transfer_required"
    SLA_RISK = "sla_risk"
    MAINTENANCE_WARNING = "maintenance_warning"
    CONSUMABLE_SHORTAGE = "consumable_shortage"
    PERSONNEL_BLOCKED = "personnel_blocked"
    REVIEW_PENDING = "review_pending"
    ORDER_BLOCKED = "order_blocked"
    AUTO_RESCHEDULE_COMPLETED = "auto_reschedule_completed"
    RETEST_REQUIRED = "retest_required"


class OperatorRequirements(BaseModel):
    required_operator_count: int = Field(default=1, ge=1)
    required_roles: list[str] = Field(default_factory=list)
    supervision_mode: SupervisionMode = SupervisionMode.SHARED_SUPERVISION
    staff_phase: StaffPhase = StaffPhase.RUNNING


class PreprocessingProfile(BaseModel):
    required_minutes: int = Field(gt=0)
    lab_area: str = Field(min_length=1, max_length=80)
    required_roles: list[str] = Field(default_factory=list)
    resource_type: str = Field(default="prep_station", min_length=1, max_length=80)
    required_operator_count: int = Field(default=1, ge=1)


class DetectionRouteStep(BaseModel):
    project_id: str = Field(min_length=1, max_length=80)
    project_type: str = Field(min_length=1, max_length=80)
    equipment_type: str = Field(min_length=1, max_length=80)
    lab_area: str = Field(default="lab", min_length=1, max_length=80)
    sequence: int = Field(ge=1)
    duration_minutes: int = Field(gt=0)
    setup_minutes: int = Field(default=0, ge=0)
    duration_profile: dict[str, int] = Field(default_factory=dict)
    staff_role: str | None = None
    operator_requirements: OperatorRequirements = Field(default_factory=OperatorRequirements)
    consumable_type: str | None = None
    consumable_units_per_batch: int = Field(default=0, ge=0)
    continuous_operation: bool = False
    can_cross_workday: bool = False


class OrderCreate(BaseModel):
    order_type: OrderType
    sample_name: str = Field(min_length=1, max_length=120)
    sample_quantity: int = Field(gt=0)
    certification_type: CertificationType
    requested_projects: list[str] = Field(default_factory=list)
    detection_route: list[DetectionRouteStep] = Field(default_factory=list)
    preprocessing_profile: PreprocessingProfile | None = None
    sample_storage_class: str | None = Field(default=None, max_length=80)
    transfer_requirements: dict[str, Any] = Field(default_factory=dict)
    arrival_time: datetime | None = None
    promised_finish_time: datetime | None = None
    parent_order_id: str | None = Field(default=None, max_length=40)
    retest_reason: str | None = Field(default=None, max_length=500)

    @field_validator("requested_projects")
    @classmethod
    def normalize_requested_projects(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class OrderUpdate(BaseModel):
    order_type: OrderType | None = None
    sample_name: str | None = Field(default=None, min_length=1, max_length=120)
    sample_quantity: int | None = Field(default=None, gt=0)
    certification_type: CertificationType | None = None
    requested_projects: list[str] | None = None
    detection_route: list[DetectionRouteStep] | None = None
    preprocessing_profile: PreprocessingProfile | None = None
    sample_storage_class: str | None = Field(default=None, max_length=80)
    transfer_requirements: dict[str, Any] | None = None
    status: QueueStatus | None = None
    arrival_time: datetime | None = None
    promised_finish_time: datetime | None = None
    parent_order_id: str | None = Field(default=None, max_length=40)
    retest_reason: str | None = Field(default=None, max_length=500)


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_type: OrderType
    sample_name: str
    sample_quantity: int
    certification_type: CertificationType
    requested_projects: list[str]
    detection_route: list[DetectionRouteStep] = Field(default_factory=list)
    preprocessing_profile: PreprocessingProfile | None = None
    sample_storage_class: str | None = None
    transfer_requirements: dict[str, Any] = Field(default_factory=dict)
    status: QueueStatus
    arrival_time: datetime | None = None
    promised_finish_time: datetime | None = None
    parent_order_id: str | None = None
    retest_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class RetestCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    requested_projects: list[str] | None = None
    promised_finish_time: datetime | None = None


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class SimulationClockAdvanceRequest(BaseModel):
    current_time: datetime | None = None
    delta_minutes: int | None = Field(default=None, ge=1)


class DatasetReplayStartRequest(BaseModel):
    speed_minutes_per_second: int = Field(default=30, ge=1, le=1440)
    max_orders: int = Field(default=500, ge=1, le=5000)
    reset_runtime: bool = True


class SchedulingEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    severity: str = Field(default="medium", min_length=1, max_length=30)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: str | None = Field(default=None, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="api", min_length=1, max_length=80)


class SchedulingEventResolve(BaseModel):
    status: SchedulingEventStatus = SchedulingEventStatus.DONE
    resolution_note: str | None = Field(default=None, max_length=500)


class SchedulingEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    severity: str
    entity_type: str | None = None
    entity_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str
    status: SchedulingEventStatus
    fingerprint: str
    debounce_until: datetime
    processed_at: datetime | None = None
    schedule_run_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    notification_type: NotificationType
    status: NotificationStatus
    severity: str
    title: str
    message: str
    order_id: str | None = None
    run_id: str | None = None
    step_position: int | None = None
    related_resource_id: str | None = None
    planned_trigger_time: datetime
    triggered_at: datetime | None = None
    read_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class StepExecutionUpdate(BaseModel):
    actual_time: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_id: str
    actor_role: str
    action: str
    target_type: str
    target_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    active: bool = True
    created_at: datetime
    updated_at: datetime


class AgentRunRequest(BaseModel):
    task_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class OfflineEvaluationRunRequest(BaseModel):
    dataset_path: str = Field(default="data/evaluation/agent_eval_cases.jsonl", min_length=1)
    limit: int | None = Field(default=None, ge=1, le=500)


class DataResponse(BaseModel):
    message: str
    data: Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"
