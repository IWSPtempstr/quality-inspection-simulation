from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from db.repositories import NotificationRepository
from domain.schemas import NotificationStatus, NotificationType


class NotificationService:
    """Build and trigger simulated employee notifications from schedule output."""

    DEFAULT_TZ = timezone(timedelta(hours=8))

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
        self.current_time: datetime | None = None

    def list_notifications(
        self,
        status: str | NotificationStatus | None = None,
        notification_type: str | NotificationType | None = None,
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            return NotificationRepository(session).list(status=status, notification_type=notification_type)

    def generate_from_schedule(self, schedule: dict, run_id: str | None = None) -> list[dict[str, Any]]:
        notifications: list[dict[str, Any]] = []
        if run_id:
            metrics = schedule.get("metrics", {})
            notifications.append(
                self._notification(
                    notification_type=NotificationType.AUTO_RESCHEDULE_COMPLETED,
                    severity="info",
                    title="自动排程已完成",
                    message=f"已生成排程批次 {run_id}，当前策略为 {metrics.get('selected_strategy', 'unknown')}。",
                    run_id=run_id,
                    planned_trigger_time=datetime.now(self.DEFAULT_TZ),
                    payload={
                        "selected_strategy": metrics.get("selected_strategy"),
                        "candidate_scores": metrics.get("candidate_scores", {}),
                    },
                )
            )
        for order in schedule.get("scheduled_orders", []):
            finish_time = self._parse_datetime(order["estimated_finish_time"])
            if order.get("sla_status") == "delayed":
                notifications.append(
                    self._notification(
                        notification_type=NotificationType.SLA_RISK,
                        severity="warning",
                        title="订单预计延期",
                        message=f"{order['sample_name']} 预计晚于承诺时间完成。",
                        order_id=order["id"],
                        run_id=run_id,
                        planned_trigger_time=finish_time,
                        payload={"delay_minutes": order.get("delay_minutes", 0)},
                    )
                )

            for index, step in enumerate(order.get("steps", []), start=1):
                step_kind = step.get("step_kind", "detection")
                start_time = self._parse_datetime(step["start_time"])
                end_time = self._parse_datetime(step["end_time"])
                if step_kind == "preprocessing":
                    notifications.append(
                        self._notification(
                            notification_type=NotificationType.SAMPLE_PREPROCESSING_TODO,
                            severity="info",
                            title="样品前处理待办",
                            message=f"{order['sample_name']} 需要进行样品前处理。",
                            order_id=order["id"],
                            run_id=run_id,
                            step_position=index,
                            related_resource_id=(step.get("resource_ids") or [None])[0],
                            planned_trigger_time=start_time,
                            payload={"lab_area": step.get("lab_area"), "assigned_employee_ids": step.get("assigned_employee_ids", [])},
                        )
                    )
                elif step_kind == "transfer":
                    notifications.append(
                        self._notification(
                            notification_type=NotificationType.SAMPLE_TRANSFER_REQUIRED,
                            severity="info",
                            title="样品转运待办",
                            message=f"{order['sample_name']} 需要转运至 {step.get('lab_area')}。",
                            order_id=order["id"],
                            run_id=run_id,
                            step_position=index,
                            related_resource_id=(step.get("resource_ids") or [None])[0],
                            planned_trigger_time=start_time,
                            payload={"lab_area": step.get("lab_area"), "assigned_employee_ids": step.get("assigned_employee_ids", [])},
                        )
                    )
                elif step_kind == "detection":
                    notifications.append(
                        self._notification(
                            notification_type=NotificationType.DETECTION_COMPLETED,
                            severity="info",
                            title="检测步骤完成",
                            message=f"{order['sample_name']} 的 {step.get('project_type')} 检测完成。",
                            order_id=order["id"],
                            run_id=run_id,
                            step_position=index,
                            related_resource_id=step.get("equipment_id"),
                            planned_trigger_time=end_time,
                            payload={"equipment_id": step.get("equipment_id"), "assigned_employee_ids": step.get("assigned_employee_ids", [])},
                        )
                    )
                    notifications.append(
                        self._notification(
                            notification_type=NotificationType.EQUIPMENT_IDLE,
                            severity="info",
                            title="设备空闲",
                            message=f"{step.get('equipment_id')} 已完成当前步骤，可接收后续任务。",
                            order_id=order["id"],
                            run_id=run_id,
                            step_position=index,
                            related_resource_id=step.get("equipment_id"),
                            planned_trigger_time=end_time,
                            payload={"equipment_type": step.get("equipment_type"), "lab_area": step.get("lab_area")},
                        )
                    )
                    if step.get("project_type") == "cb_review":
                        notifications.append(
                            self._notification(
                                notification_type=NotificationType.REVIEW_PENDING,
                                severity="info",
                                title="认证资料复核待办",
                                message=f"{order['sample_name']} 进入国际认证资料复核环节。",
                                order_id=order["id"],
                                run_id=run_id,
                                step_position=index,
                                related_resource_id=step.get("equipment_id"),
                                planned_trigger_time=end_time,
                                payload={"project_type": step.get("project_type")},
                            )
                        )

        for order in schedule.get("blocked_orders", []):
            reason = order.get("reason", "")
            notification_type = NotificationType.ORDER_BLOCKED
            if "personnel" in reason:
                notification_type = NotificationType.PERSONNEL_BLOCKED
            if "consumable" in reason:
                notification_type = NotificationType.CONSUMABLE_SHORTAGE
            notifications.append(
                self._notification(
                    notification_type=notification_type,
                    severity="warning",
                    title="订单排程阻塞",
                    message=f"{order['sample_name']} 当前无法完成排程：{reason}",
                    order_id=order["id"],
                    run_id=run_id,
                    planned_trigger_time=self._parse_datetime(order.get("arrival_time") or datetime.now(self.DEFAULT_TZ)),
                    payload={"reason": reason},
                )
            )

        if not notifications:
            return []
        with self.session_factory() as session:
            return NotificationRepository(session).create_many(notifications)

    def advance_clock(self, current_time: datetime | None = None, delta_minutes: int | None = None) -> dict[str, Any]:
        if current_time is not None:
            resolved = self._parse_datetime(current_time)
        elif delta_minutes is not None:
            resolved = (self.current_time or datetime.now(self.DEFAULT_TZ)) + timedelta(minutes=delta_minutes)
        else:
            resolved = datetime.now(self.DEFAULT_TZ)
        self.current_time = resolved
        with self.session_factory() as session:
            triggered = NotificationRepository(session).trigger_due(resolved)
        return {"current_time": resolved, "triggered_count": len(triggered), "triggered_notifications": triggered}

    def clock(self) -> dict[str, Any]:
        return {"current_time": self.current_time}

    def mark_read(self, notification_id: str, read_at: datetime | None = None) -> dict[str, Any] | None:
        with self.session_factory() as session:
            return NotificationRepository(session).mark_read(notification_id, self._parse_datetime(read_at or datetime.now(self.DEFAULT_TZ)))

    def stream_events(self) -> str:
        notifications = self.list_notifications(status=NotificationStatus.TRIGGERED)
        if not notifications:
            notifications = self.list_notifications()
        payload = notifications[0] if notifications else {"notification_type": "heartbeat", "status": "empty"}
        return f"data: {json.dumps(self._json_ready(payload), ensure_ascii=False)}\n\n"

    def _notification(
        self,
        notification_type: NotificationType,
        severity: str,
        title: str,
        message: str,
        planned_trigger_time: datetime,
        order_id: str | None = None,
        run_id: str | None = None,
        step_position: int | None = None,
        related_resource_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "notification_type": notification_type,
            "status": NotificationStatus.PENDING,
            "severity": severity,
            "title": title,
            "message": message,
            "order_id": order_id,
            "run_id": run_id,
            "step_position": step_position,
            "related_resource_id": related_resource_id,
            "planned_trigger_time": planned_trigger_time,
            "payload": payload or {},
        }

    def _parse_datetime(self, value) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=self.DEFAULT_TZ)
            return value
        return datetime.fromisoformat(value)

    def _json_ready(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._json_ready(item) for item in value]
        if isinstance(value, dict):
            return {key: self._json_ready(item) for key, item in value.items()}
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value
