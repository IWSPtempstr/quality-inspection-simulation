from __future__ import annotations

from fastapi import APIRouter, Query, Request

from domain.schemas import DataResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=DataResponse)
def list_users(request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "audit:read")
    return DataResponse(message="用户权限查询成功", data=request.app.state.audit_service.users())


@router.get("/audit-logs", response_model=DataResponse)
def list_audit_logs(
    request: Request,
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
) -> DataResponse:
    request.app.state.permission_service.require(request, "audit:read")
    return DataResponse(
        message="操作审计查询成功",
        data=request.app.state.audit_service.list_logs(
            action=action,
            target_type=target_type,
            target_id=target_id,
        ),
    )
