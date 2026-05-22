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


class DetectionRouteStep(BaseModel):
    project_id: str = Field(min_length=1, max_length=80)
    project_type: str = Field(min_length=1, max_length=80)
    equipment_type: str = Field(min_length=1, max_length=80)
    sequence: int = Field(ge=1)
    duration_minutes: int = Field(gt=0)
    duration_profile: dict[str, int] = Field(default_factory=dict)
    staff_role: str | None = None


class OrderCreate(BaseModel):
    order_type: OrderType
    sample_name: str = Field(min_length=1, max_length=120)
    sample_quantity: int = Field(gt=0)
    certification_type: CertificationType
    requested_projects: list[str] = Field(default_factory=list)
    detection_route: list[DetectionRouteStep] = Field(default_factory=list)
    arrival_time: datetime | None = None
    promised_finish_time: datetime | None = None

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
    status: QueueStatus | None = None
    arrival_time: datetime | None = None
    promised_finish_time: datetime | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_type: OrderType
    sample_name: str
    sample_quantity: int
    certification_type: CertificationType
    requested_projects: list[str]
    detection_route: list[DetectionRouteStep] = Field(default_factory=list)
    status: QueueStatus
    arrival_time: datetime | None = None
    promised_finish_time: datetime | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class AgentRunRequest(BaseModel):
    task_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class DataResponse(BaseModel):
    message: str
    data: Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"
