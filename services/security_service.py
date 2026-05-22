from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from db.repositories import AuditLogRepository, UserRepository


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str


class PermissionService:
    """Header-based permission shim for simulation and auditability."""

    ROLE_PERMISSIONS = {
        "admin": {"*"},
        "scheduler": {"orders:write", "schedule:write", "events:resolve", "audit:read"},
        "operator": {"execution:write", "notifications:read"},
        "viewer": {"orders:read", "schedule:read"},
    }

    def actor_from_request(self, request: Request) -> Actor:
        return Actor(
            actor_id=request.headers.get("X-User-Id", "admin"),
            role=request.headers.get("X-User-Role", "admin"),
        )

    def require(self, request: Request, permission: str) -> Actor:
        actor = self.actor_from_request(request)
        permissions = self.ROLE_PERMISSIONS.get(actor.role, set())
        if "*" not in permissions and permission not in permissions:
            raise HTTPException(status_code=403, detail=f"缺少权限: {permission}")
        return actor


class AuditService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def record(
        self,
        request: Request,
        action: str,
        target_type: str,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict:
        actor = request.app.state.permission_service.actor_from_request(request)
        with self.session_factory() as session:
            return AuditLogRepository(session).add(
                actor_id=actor.actor_id,
                actor_role=actor.role,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail or {},
            )

    def list_logs(
        self,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[dict]:
        with self.session_factory() as session:
            return AuditLogRepository(session).list(
                action=action,
                target_type=target_type,
                target_id=target_id,
            )

    def users(self) -> list[dict]:
        with self.session_factory() as session:
            return UserRepository(session).list_all()
