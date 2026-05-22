from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from domain.schemas import DataResponse

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=DataResponse)
def list_notifications(
    request: Request,
    status: str | None = Query(default=None),
    notification_type: str | None = Query(default=None),
) -> DataResponse:
    request.app.state.permission_service.require(request, "notifications:read")
    return DataResponse(
        message="通知查询成功",
        data=request.app.state.notification_service.list_notifications(
            status=status,
            notification_type=notification_type,
        ),
    )


@router.patch("/{notification_id}/read", response_model=DataResponse)
def mark_notification_read(notification_id: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "notifications:read")
    notification = request.app.state.notification_service.mark_read(notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    request.app.state.audit_service.record(
        request,
        action="notification_read",
        target_type="notification",
        target_id=notification_id,
        detail={"notification_type": notification["notification_type"].value if hasattr(notification["notification_type"], "value") else notification["notification_type"]},
    )
    return DataResponse(message="通知已标记为已读", data=notification)


@router.get("/stream")
def stream_notifications(request: Request) -> StreamingResponse:
    def event_stream():
        yield request.app.state.notification_service.stream_events()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
