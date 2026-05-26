from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from db.repositories import (
    OrderRepository,
    ScheduleRepository,
    SchedulingEventRepository,
)
from domain.schemas import (
    SchedulingEventCreate,
    SchedulingEventStatus,
)
from services.notification_service import NotificationService
from services.queue_service import QueueService
from services.schedule_formatter import format_schedule_detail


class ScheduleOptimizerService:
    STRATEGIES = [
        "priority_fifo",
        "earliest_due_date",
        "shortest_processing_time",
        "bottleneck_resource_first",
        "hybrid_weighted",
        "sla_guarded_hybrid",
        "cp_sat_rolling",
    ]

    def __init__(self, queue_service: QueueService, default_strategy: str = "hybrid_weighted") -> None:
        self.queue_service = queue_service
        self.default_strategy = default_strategy

    def analyze(self, orders: list[dict], strategy: str | None = None, locked_steps: list[dict] | None = None) -> dict[str, Any]:
        strategies = [strategy] if strategy else list(self.STRATEGIES)
        candidate_scores: dict[str, float] = {}
        candidates: dict[str, dict] = {}
        for item in strategies:
            schedule = self.queue_service.rebuild_schedule(orders, strategy=item, locked_steps=locked_steps or [])
            score = self._score_schedule(schedule)
            candidate_scores[item] = score
            candidates[item] = schedule

        selected_strategy = min(candidate_scores, key=candidate_scores.get) if candidate_scores else self.default_strategy
        selected_schedule = candidates[selected_strategy] if candidates else self.queue_service.rebuild_schedule(orders, strategy=self.default_strategy, locked_steps=locked_steps or [])
        selected_schedule["metrics"] = {
            **selected_schedule.get("metrics", {}),
            "selected_strategy": selected_strategy,
            "candidate_scores": candidate_scores,
        }
        return {
            "selected_strategy": selected_strategy,
            "candidate_scores": candidate_scores,
            "candidates": candidates,
            "schedule": selected_schedule,
        }

    def _score_schedule(self, schedule: dict) -> float:
        metrics = schedule.get("metrics", {})
        blocked = float(metrics.get("blocked_count", 0))
        delayed = float(metrics.get("delayed_count", 0))
        vip_delayed = float(metrics.get("vip_delayed_count", 0))
        urgent_delayed = float(metrics.get("urgent_delayed_count", 0))
        normal_delayed = float(metrics.get("normal_delayed_count", 0))
        total_delay = float(metrics.get("total_delay_minutes", 0))
        vip_delay = float(metrics.get("vip_delay_minutes", 0))
        urgent_delay = float(metrics.get("urgent_delay_minutes", 0))
        normal_delay = float(metrics.get("normal_delay_minutes", 0))
        average_wait = float(metrics.get("average_wait_minutes", 0))
        equipment_idle = float(metrics.get("equipment_idle_penalty", 0))
        personnel_blocked = float(metrics.get("personnel_blocked_count", 0))
        transfer_wait = float(metrics.get("transfer_wait_minutes", 0))
        forecast = float(metrics.get("forecast_count", 0))
        return (
            blocked * 10_000_000
            + forecast * 1_000_000_000
            + vip_delayed * 5_000_000
            + urgent_delayed * 1_000_000
            + normal_delayed * 100_000
            + delayed * 50_000
            + vip_delay * 2_000
            + urgent_delay * 800
            + normal_delay * 50
            + total_delay * 20
            + average_wait * 10
            + equipment_idle * 50
            + personnel_blocked * 200
            + transfer_wait * 50
        )


class SchedulingEventService:
    DEFAULT_TZ = timezone(timedelta(hours=8))

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        debounce_seconds: int = 30,
        immediate_severities: set[str] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.debounce_seconds = debounce_seconds
        self.immediate_severities = immediate_severities or {"critical", "high"}

    def record_event(self, payload: SchedulingEventCreate, now: datetime | None = None) -> dict:
        current = self._ensure_tz(now or datetime.now(self.DEFAULT_TZ))
        fingerprint = self._fingerprint(payload)
        debounce_until = current + timedelta(seconds=self.debounce_seconds)
        with self.session_factory() as session:
            repository = SchedulingEventRepository(session)
            duplicate = repository.find_active_duplicate(fingerprint, current)
            if duplicate:
                return repository.create(
                    payload,
                    fingerprint=fingerprint,
                    debounce_until=debounce_until,
                    status=SchedulingEventStatus.IGNORED,
                    processed_at=current,
                    error_message="debounced_duplicate",
                )
            return repository.create(
                payload,
                fingerprint=fingerprint,
                debounce_until=debounce_until,
            )

    def should_trigger_immediately(self, event: dict) -> bool:
        return (
            event.get("status") == SchedulingEventStatus.PENDING.value
            and str(event.get("severity", "")).lower() in self.immediate_severities
        )

    def create_order_event(self, order: dict, event_type: str) -> dict:
        payload = SchedulingEventCreate(
            event_type=event_type,
            severity="medium",
            entity_type="order",
            entity_id=order["id"],
            payload={
                "order_type": order.get("order_type"),
                "certification_type": order.get("certification_type"),
                "sample_quantity": order.get("sample_quantity"),
            },
            source="api",
        )
        return self.record_event(payload)

    def create_update_event(self, order: dict, changes: dict) -> dict | None:
        if not changes:
            return None
        if "order_type" in changes:
            event_type = "order_priority_changed"
        elif "detection_route" in changes:
            event_type = "order_route_changed"
        else:
            event_type = "order_updated"
        payload = SchedulingEventCreate(
            event_type=event_type,
            severity="medium",
            entity_type="order",
            entity_id=order["id"],
            payload={"changes": changes},
            source="api",
        )
        return self.record_event(payload)

    def list_events(
        self,
        status: str | SchedulingEventStatus | None = None,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> list[dict]:
        with self.session_factory() as session:
            return SchedulingEventRepository(session).list(
                status=status,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
            )

    def pending_count(self) -> int:
        with self.session_factory() as session:
            return SchedulingEventRepository(session).count_pending()

    def pending_events(self, now: datetime | None = None) -> list[dict]:
        current = self._ensure_tz(now or datetime.now(self.DEFAULT_TZ))
        with self.session_factory() as session:
            return SchedulingEventRepository(session).pending_due(current)

    def _fingerprint(self, payload: SchedulingEventCreate) -> str:
        import json

        payload_items = json.dumps(payload.payload, ensure_ascii=False, sort_keys=True)
        return f"{payload.event_type}|{payload.entity_type}|{payload.entity_id}|{payload.source}|{payload.severity}|{payload_items}"

    def _ensure_tz(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=self.DEFAULT_TZ)
        return value


class SchedulingCoordinatorService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        queue_service: QueueService,
        notification_service: NotificationService,
        event_service: SchedulingEventService,
        optimizer: ScheduleOptimizerService,
    ) -> None:
        self.session_factory = session_factory
        self.queue_service = queue_service
        self.notification_service = notification_service
        self.event_service = event_service
        self.optimizer = optimizer

    def rebuild(
        self,
        trigger_source: str,
        requested_strategy: str | None = None,
        trigger_event_ids: list[str] | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if trigger_event_ids is None:
            trigger_event_ids = [item["id"] for item in self.event_service.pending_events()]
        with self.session_factory() as session:
            orders = OrderRepository(session).list_active()
            locked_order_ids = {
                order["id"]
                for order in orders
                if self._enum_value(order.get("status")) == "running"
            }
            schedulable_orders = [
                order
                for order in orders
                if self._enum_value(order.get("status")) not in {"running", "completed"}
            ]
            locked_orders = self._locked_schedule_orders(session, locked_order_ids)
            locked_steps = self._locked_schedule_steps(locked_orders)
            analysis = self.optimizer.analyze(schedulable_orders, strategy=requested_strategy, locked_steps=locked_steps)
            schedule = analysis["schedule"]
            if locked_orders:
                schedule["scheduled_orders"] = [
                    *locked_orders,
                    *[
                        order
                        for order in schedule.get("scheduled_orders", [])
                        if order["id"] not in locked_order_ids
                    ],
                ]
                schedule.setdefault("metrics", {})["locked_running_count"] = len(locked_orders)
            persisted = ScheduleRepository(session).create_from_schedule(schedule)
            notification_payload = self.notification_service.generate_from_schedule(schedule, run_id=persisted["id"])
            if trigger_event_ids:
                from db.repositories import SchedulingEventRepository

                SchedulingEventRepository(session).mark_done(trigger_event_ids, persisted["id"], self._now())
            self.queue_service.last_schedule = schedule
            return {
                "trigger_source": trigger_source,
                "run": persisted,
                "schedule": schedule,
                "analysis": {
                    "selected_strategy": analysis["selected_strategy"],
                    "candidate_scores": analysis["candidate_scores"],
                    "explanation": self._build_explanation(analysis),
                    "candidates": {
                        name: self._summarize_candidate(value) for name, value in analysis["candidates"].items()
                    },
                },
                "notifications": notification_payload,
                "extra_payload": extra_payload or {},
            }

    def query_latest(self, session: Session) -> dict | None:
        repository = ScheduleRepository(session)
        latest = repository.latest()
        return repository.get(latest["id"]) if latest else None

    def heartbeat_once(self, now: datetime | None = None) -> dict[str, Any]:
        current = self._now(now)
        pending = self.event_service.pending_events(current)
        if not pending:
            return {
                "triggered": False,
                "reason": "no_pending_events",
                "pending_event_count": 0,
                "processed_event_count": 0,
                "schedule_run_id": None,
                "visited_agents": ["queue_scheduler"],
            }
        event_ids = [item["id"] for item in pending]
        with self.session_factory() as session:
            SchedulingEventRepository(session).mark_processing(event_ids, current)
        try:
            result = self.rebuild(
                trigger_source="heartbeat",
                trigger_event_ids=event_ids,
                extra_payload={"pending_event_count": len(pending)},
            )
            return {
                "triggered": True,
                "reason": "pending_events_processed",
                "pending_event_count": len(pending),
                "processed_event_count": len(event_ids),
                "schedule_run_id": result["run"]["id"],
                "selected_strategy": result["analysis"]["selected_strategy"],
                "candidate_scores": result["analysis"]["candidate_scores"],
                "visited_agents": ["queue_scheduler"],
                "result": result,
            }
        except Exception as exc:  # noqa: BLE001
            with self.session_factory() as session:
                SchedulingEventRepository(session).mark_failed(event_ids, str(exc), current)
            raise

    def heartbeat_status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "interval_seconds": 30,
            "pending_event_count": self.event_service.pending_count(),
            "last_run_at": None,
            "running": False,
        }

    def analyze_options(self, requested_strategy: str | None = None) -> dict[str, Any]:
        with self.session_factory() as session:
            orders = [
                order
                for order in OrderRepository(session).list_active()
                if self._enum_value(order.get("status")) not in {"running", "completed"}
            ]
        analysis = self.optimizer.analyze(orders, strategy=requested_strategy)
        return {
            "analysis": {
                "selected_strategy": analysis["selected_strategy"],
                "candidate_scores": analysis["candidate_scores"],
                "explanation": self._build_explanation(analysis),
                "candidates": {
                    name: self._summarize_candidate(value) for name, value in analysis["candidates"].items()
                },
            }
        }

    def _summarize_candidate(self, schedule: dict) -> dict:
        metrics = schedule.get("metrics", {})
        return {
            "scheduled_count": len(schedule.get("scheduled_orders", [])),
            "blocked_count": len(schedule.get("blocked_orders", [])),
            "metrics": {
                "total_delay_minutes": metrics.get("total_delay_minutes", 0),
                "vip_delay_minutes": metrics.get("vip_delay_minutes", 0),
                "urgent_delay_minutes": metrics.get("urgent_delay_minutes", 0),
                "normal_delay_minutes": metrics.get("normal_delay_minutes", 0),
                "on_time_rate": metrics.get("on_time_rate", 0),
                "vip_sla_rate": metrics.get("vip_sla_rate", 0),
                "urgent_delay_rate": metrics.get("urgent_delay_rate", 0),
                "delayed_count": metrics.get("delayed_count", 0),
                "vip_delayed_count": metrics.get("vip_delayed_count", 0),
                "urgent_delayed_count": metrics.get("urgent_delayed_count", 0),
                "average_wait_minutes": metrics.get("average_wait_minutes", 0),
                "personnel_blocked_count": metrics.get("personnel_blocked_count", 0),
                "transfer_wait_minutes": metrics.get("transfer_wait_minutes", 0),
            },
        }

    def _locked_schedule_orders(self, session: Session, locked_order_ids: set[str]) -> list[dict[str, Any]]:
        if not locked_order_ids:
            return []
        latest = ScheduleRepository(session).latest()
        if not latest:
            return []
        detail = ScheduleRepository(session).get(latest["id"])
        if not detail:
            return []
        formatted = format_schedule_detail(detail)
        locked = []
        for order in formatted.get("scheduled_orders", []):
            if order["id"] in locked_order_ids:
                order["status"] = "running"
                if order.get("steps"):
                    last_step = max(order["steps"], key=lambda item: item.get("end_minute") or 0)
                    order["estimated_finish_time"] = last_step.get("end_time")
                    order["estimated_finish_minute"] = last_step.get("end_minute")
                for step in order.get("steps", []):
                    if step.get("execution_status") == "running":
                        step["locked"] = True
                locked.append(order)
        return locked

    def _locked_schedule_steps(self, locked_orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            step
            for order in locked_orders
            for step in order.get("steps", [])
            if step.get("locked") or step.get("execution_status") == "running"
        ]

    def _build_explanation(self, analysis: dict[str, Any]) -> dict[str, Any]:
        selected_strategy = analysis["selected_strategy"]
        selected_score = analysis["candidate_scores"].get(selected_strategy, 0)
        ranked = [
            {"strategy": name, "score": score, "delta_from_selected": round(score - selected_score, 2)}
            for name, score in sorted(analysis["candidate_scores"].items(), key=lambda item: item[1])
        ]
        selected = analysis["schedule"]
        metrics = selected.get("metrics", {})
        utilization = metrics.get("equipment_utilization", {})
        bottlenecks = sorted(utilization.items(), key=lambda item: item[1], reverse=True)[:5]
        capacity_analysis = metrics.get("capacity_analysis", {})
        over_capacity = [
            {
                "equipment_type": equipment_type,
                **analysis,
            }
            for equipment_type, analysis in capacity_analysis.items()
            if float(analysis.get("load_factor", 0)) > 1.0
        ]
        delayed_orders = [
            {
                "order_id": order["id"],
                "order_type": order["order_type"],
                "sample_name": order["sample_name"],
                "delay_minutes": order.get("delay_minutes", 0),
            }
            for order in selected.get("scheduled_orders", [])
            if int(order.get("delay_minutes") or 0) > 0
        ][:10]
        return {
            "selected_strategy": selected_strategy,
            "strategy_rankings": ranked,
            "bottleneck_resources": [
                {"resource_id": resource_id, "utilization": value}
                for resource_id, value in bottlenecks
            ],
            "sla_risks": {
                "on_time_rate": metrics.get("on_time_rate", 0),
                "vip_delay_minutes": metrics.get("vip_delay_minutes", 0),
                "urgent_delay_minutes": metrics.get("urgent_delay_minutes", 0),
                "normal_delay_minutes": metrics.get("normal_delay_minutes", 0),
                "top_delayed_orders": delayed_orders,
            },
            "blocking": {
                "blocked_count": len(selected.get("blocked_orders", [])),
                "blocked_reason_distribution": metrics.get("blocked_reason_distribution", {}),
                "personnel_blocked_count": metrics.get("personnel_blocked_count", 0),
            },
            "capacity_risks": {
                "over_capacity_resources": over_capacity,
                "expansion_recommendations": [
                    {
                        "equipment_type": item["equipment_type"],
                        "current_instances": item.get("instances", 0),
                        "recommended_instances": item.get("recommended_instances_for_90pct", 0),
                    }
                    for item in over_capacity
                ],
            },
        }

    def _now(self, value: datetime | None = None) -> datetime:
        if value is None:
            value = datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def _enum_value(self, value):
        return value.value if hasattr(value, "value") else value


class SchedulerHeartbeatService:
    def __init__(
        self,
        coordinator: SchedulingCoordinatorService,
        enabled: bool = True,
        interval_seconds: int = 30,
    ) -> None:
        self.coordinator = coordinator
        self.enabled = enabled
        self.interval_seconds = max(1, interval_seconds)
        self._lock = threading.Lock()
        self._last_run_at: datetime | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def trigger(self, now: datetime | None = None) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            return {
                "triggered": False,
                "reason": "already_running",
                "pending_event_count": self.coordinator.event_service.pending_count(),
                "processed_event_count": 0,
                "schedule_run_id": None,
                "visited_agents": ["queue_scheduler"],
            }
        try:
            result = self.coordinator.heartbeat_once(now)
            self._last_run_at = self.coordinator._now(now)
            self._last_result = result
            self._last_error = None
            return result
        finally:
            self._lock.release()

    def start_background_loop(self) -> None:
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_background_loop,
            name="scheduler-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop_background_loop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run_background_loop(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.trigger()
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "pending_event_count": self.coordinator.event_service.pending_count(),
            "last_run_at": self._last_run_at,
            "running": self._lock.locked(),
            "background_running": bool(self._thread and self._thread.is_alive()),
            "last_error": self._last_error,
            "last_result": self._last_result,
        }
