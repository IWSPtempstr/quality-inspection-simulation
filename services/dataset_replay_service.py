from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from db.repositories import (
    DatasetReplayRepository,
    OrderRepository,
    RuntimeRepository,
)
from domain.schemas import (
    DatasetReplayStartRequest,
    DatasetReplayStatus,
    OrderCreate,
    SchedulingEventCreate,
)


class DatasetReplayService:
    DEFAULT_TZ = timezone(timedelta(hours=8))
    FALLBACK_START = datetime(2026, 6, 1, 9, 0, tzinfo=DEFAULT_TZ)

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        base_dir: Path,
        scheduling_event_service,
        scheduler_heartbeat_service,
        notification_service,
    ) -> None:
        self.session_factory = session_factory
        self.base_dir = base_dir
        self.data_dir = base_dir / "data"
        self.scheduling_event_service = scheduling_event_service
        self.scheduler_heartbeat_service = scheduler_heartbeat_service
        self.notification_service = notification_service

    def list_datasets(self) -> dict[str, Any]:
        items = []
        for dataset_dir in sorted(self.data_dir.iterdir() if self.data_dir.exists() else []):
            if not dataset_dir.is_dir():
                continue
            if not self._orders_file(dataset_dir):
                continue
            items.append(self.summary(dataset_dir.name))
        return {"items": items, "total": len(items)}

    def summary(self, dataset_name: str) -> dict[str, Any]:
        dataset_dir = self._dataset_dir(dataset_name)
        orders = self._load_orders(dataset_dir)
        normalized = self._normalized_orders(orders)
        order_types = Counter(order.get("order_type") for order in normalized)
        certification_types = Counter(order.get("certification_type") for order in normalized)
        route_lengths = [len(order.get("detection_route") or []) for order in normalized]
        manifest = self._read_json(dataset_dir / "dataset_manifest.json")
        start_time = normalized[0]["arrival_time"] if normalized else None
        end_time = normalized[-1]["arrival_time"] if normalized else None
        return {
            "name": dataset_dir.name,
            "dataset": dataset_dir.name,
            "version": manifest.get("dataset_version") or manifest.get("version"),
            "synthetic": manifest.get("synthetic", True),
            "order_count": len(normalized),
            "start_time": start_time,
            "end_time": end_time,
            "order_type_distribution": dict(order_types),
            "certification_distribution": dict(certification_types),
            "max_route_length": max(route_lengths) if route_lengths else 0,
            "files": {
                "orders": self._orders_file(dataset_dir).name,
                "manifest": "dataset_manifest.json" if (dataset_dir / "dataset_manifest.json").exists() else None,
            },
            "usage_boundary": manifest.get("usage_boundary") or "合成或最小验证数据，仅用于系统机制验证。",
        }

    def start(self, dataset_name: str, request: DatasetReplayStartRequest) -> dict[str, Any]:
        dataset_dir = self._dataset_dir(dataset_name)
        orders = self._normalized_orders(self._load_orders(dataset_dir))
        if not orders:
            raise ValueError("数据集没有可回放订单")
        selected_orders = orders[: min(request.max_orders, len(orders))]
        start_time = self._parse_datetime(selected_orders[0]["arrival_time"])
        end_time = self._parse_datetime(selected_orders[-1]["arrival_time"])

        with self.session_factory() as session:
            if request.reset_runtime:
                RuntimeRepository(session).clear_runtime(include_replay=True)
            repository = DatasetReplayRepository(session)
            run = repository.create_run(
                dataset_name=dataset_name,
                total_orders=len(selected_orders),
                start_time=start_time,
                end_time=end_time,
                speed_minutes_per_second=request.speed_minutes_per_second,
            )
            repository.create_items(run["id"], selected_orders)

        self.notification_service.advance_clock(current_time=start_time)
        return self.get(run["id"])

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            return DatasetReplayRepository(session).get_run_with_items(run_id)

    def latest(self) -> dict[str, Any] | None:
        with self.session_factory() as session:
            latest = DatasetReplayRepository(session).latest_run()
            return DatasetReplayRepository(session).get_run_with_items(latest["id"]) if latest else None

    def tick(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            repository = DatasetReplayRepository(session)
            run = repository.get_run(run_id)
            if run is None:
                return None
            if run["status"] == DatasetReplayStatus.PAUSED.value:
                return repository.get_run_with_items(run_id)
            if run["status"] in {
                DatasetReplayStatus.COMPLETED.value,
                DatasetReplayStatus.FAILED.value,
                DatasetReplayStatus.CANCELLED.value,
            }:
                return repository.get_run_with_items(run_id)
            current_time = self._parse_datetime(run["current_simulation_time"]) + timedelta(
                minutes=int(run["speed_minutes_per_second"])
            )
            repository.update_run(
                run_id,
                status=DatasetReplayStatus.RUNNING,
                current_simulation_time=current_time,
            )
            due_items = repository.due_items(run_id, current_time)

        return self._import_and_schedule(run_id, due_items, current_time, action="tick")

    def step(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            repository = DatasetReplayRepository(session)
            run = repository.get_run(run_id)
            if run is None:
                return None
            if run["status"] in {
                DatasetReplayStatus.COMPLETED.value,
                DatasetReplayStatus.FAILED.value,
                DatasetReplayStatus.CANCELLED.value,
            }:
                return repository.get_run_with_items(run_id)
            item = repository.next_pending_item(run_id)
            if item is None:
                completed = repository.update_run(run_id, status=DatasetReplayStatus.COMPLETED)
                return repository.get_run_with_items(completed["id"]) if completed else None
            current_time = self._parse_datetime(item["arrival_time"])
            repository.update_run(
                run_id,
                status=DatasetReplayStatus.RUNNING,
                current_simulation_time=current_time,
            )

        return self._import_and_schedule(run_id, [item], current_time, action="step")

    def pause(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            repository = DatasetReplayRepository(session)
            run = repository.update_run(run_id, status=DatasetReplayStatus.PAUSED)
            return repository.get_run_with_items(run["id"]) if run else None

    def resume(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            repository = DatasetReplayRepository(session)
            run = repository.get_run(run_id)
            if run is None:
                return None
            if run["status"] == DatasetReplayStatus.PAUSED.value:
                repository.update_run(run_id, status=DatasetReplayStatus.RUNNING)
            return repository.get_run_with_items(run_id)

    def stream_events(self, run_id: str) -> str:
        run = self.get(run_id)
        payload = run or {"id": run_id, "status": "missing"}
        return f"data: {json.dumps(self._json_ready(payload), ensure_ascii=False)}\n\n"

    def _import_and_schedule(
        self,
        run_id: str,
        items: list[dict[str, Any]],
        current_time: datetime,
        action: str,
    ) -> dict[str, Any] | None:
        latest_order_id = None
        latest_source_order_id = None
        imported_count = 0
        try:
            for item in items:
                try:
                    order = self._import_one_item(item, current_time)
                except Exception as exc:  # noqa: BLE001
                    with self.session_factory() as session:
                        DatasetReplayRepository(session).mark_item_failed(item["id"], str(exc), current_time)
                    raise
                latest_order_id = order["id"]
                latest_source_order_id = item["original_order_id"]
                imported_count += 1

            heartbeat = self.scheduler_heartbeat_service.trigger(now=current_time) if imported_count else None
            latest_schedule_run_id = heartbeat.get("schedule_run_id") if heartbeat else None
            with self.session_factory() as session:
                repository = DatasetReplayRepository(session)
                total_imported = repository.imported_count(run_id)
                run = repository.get_run(run_id)
                status = DatasetReplayStatus.COMPLETED if total_imported >= int(run["total_orders"]) else DatasetReplayStatus.RUNNING
                updated = repository.update_run(
                    run_id,
                    status=status,
                    current_simulation_time=current_time,
                    imported_orders=total_imported,
                    latest_order_id=latest_order_id,
                    latest_source_order_id=latest_source_order_id,
                    latest_schedule_run_id=latest_schedule_run_id,
                )
                detail = repository.get_run_with_items(updated["id"]) if updated else None
            if detail is not None:
                detail["last_action"] = action
                detail["imported_this_tick"] = imported_count
                detail["heartbeat"] = heartbeat
            self.notification_service.advance_clock(current_time=current_time)
            return detail
        except Exception as exc:  # noqa: BLE001
            with self.session_factory() as session:
                repository = DatasetReplayRepository(session)
                repository.update_run(run_id, status=DatasetReplayStatus.FAILED, error_message=str(exc))
                failed = repository.get_run_with_items(run_id)
            if failed is not None:
                failed["last_action"] = action
            return failed

    def _import_one_item(self, item: dict[str, Any], imported_at: datetime) -> dict[str, Any]:
        payload = dict(item["original_payload"])
        payload["arrival_time"] = item["arrival_time"]
        order_payload = self._order_payload(payload)
        with self.session_factory() as session:
            order = OrderRepository(session).create(OrderCreate.model_validate(order_payload))
            DatasetReplayRepository(session).mark_item_imported(item["id"], order.id, imported_at)
        event = self.scheduling_event_service.record_event(
            SchedulingEventCreate(
                event_type="order_created",
                severity="medium",
                entity_type="order",
                entity_id=order.id,
                payload={
                    "dataset_replay_run_id": item["run_id"],
                    "source_order_id": item["original_order_id"],
                    "order_type": order.order_type.value,
                    "certification_type": order.certification_type.value,
                    "sample_quantity": order.sample_quantity,
                },
                source="dataset_replay",
            ),
            now=imported_at,
        )
        return {**order.model_dump(mode="json"), "event_id": event["id"]}

    def _dataset_dir(self, dataset_name: str) -> Path:
        if "/" in dataset_name or "\\" in dataset_name or dataset_name.startswith("."):
            raise FileNotFoundError(dataset_name)
        dataset_dir = self.data_dir / dataset_name
        if not dataset_dir.exists() or not dataset_dir.is_dir() or not self._orders_file(dataset_dir):
            raise FileNotFoundError(dataset_name)
        return dataset_dir

    def _orders_file(self, dataset_dir: Path) -> Path | None:
        for filename in ("order_arrivals.json", "orders.json"):
            path = dataset_dir / filename
            if path.exists():
                return path
        return None

    def _load_orders(self, dataset_dir: Path) -> list[dict[str, Any]]:
        path = self._orders_file(dataset_dir)
        if path is None:
            return []
        data = self._read_json(path)
        if isinstance(data, dict):
            data = data.get("orders", [])
        return [item for item in data if isinstance(item, dict)]

    def _normalized_orders(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for index, order in enumerate(orders):
            item = dict(order)
            if not item.get("arrival_time"):
                item["arrival_time"] = (self.FALLBACK_START + timedelta(minutes=index * 10)).isoformat()
            if not item.get("order_id"):
                item["order_id"] = f"dataset-order-{index + 1:05d}"
            normalized.append(item)
        return sorted(normalized, key=lambda item: self._parse_datetime(item["arrival_time"]))

    def _order_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "order_type": payload["order_type"],
            "sample_name": payload["sample_name"],
            "sample_quantity": payload["sample_quantity"],
            "certification_type": payload["certification_type"],
            "requested_projects": payload.get("requested_projects") or [],
            "detection_route": payload.get("detection_route") or [],
            "preprocessing_profile": payload.get("preprocessing_profile"),
            "sample_storage_class": payload.get("sample_storage_class"),
            "transfer_requirements": payload.get("transfer_requirements") or {},
            "arrival_time": self._parse_datetime(payload["arrival_time"]),
            "promised_finish_time": self._parse_datetime(payload["promised_finish_time"]) if payload.get("promised_finish_time") else None,
        }

    def _read_json(self, path: Path) -> Any:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _parse_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            resolved = value
        else:
            resolved = datetime.fromisoformat(str(value))
        if resolved.tzinfo is None:
            return resolved.replace(tzinfo=self.DEFAULT_TZ)
        return resolved

    def _json_ready(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._json_ready(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_ready(item) for item in value]
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "value"):
            return value.value
        return value
