from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from db.repositories import ScheduleRepository, SchedulingEventRepository
from services.schedule_formatter import format_gantt, format_schedule_detail


class MonitoringReportService:
    def __init__(self, session_factory: sessionmaker[Session], base_dir: Path) -> None:
        self.session_factory = session_factory
        self.base_dir = base_dir
        self._dataset_cache: dict[str, tuple[tuple[float | None, ...], dict[str, Any]]] = {}
        self._dataset_hits = 0
        self._dataset_misses = 0

    def report(self) -> dict[str, Any]:
        with self.session_factory() as session:
            repository = ScheduleRepository(session)
            latest = repository.latest()
            detail = repository.get(latest["id"]) if latest else None
            events = SchedulingEventRepository(session).list()

        formatted = format_schedule_detail(detail) if detail else None
        metrics = formatted.get("metrics", {}) if formatted else {}
        event_distribution = Counter(item["status"] for item in events)
        return {
            "latest_schedule": {
                "run_id": formatted.get("id") if formatted else None,
                "scheduled_count": formatted.get("scheduled_count", 0) if formatted else 0,
                "blocked_count": formatted.get("blocked_count", 0) if formatted else 0,
                "created_at": formatted.get("created_at") if formatted else None,
                "metrics": metrics,
                "gantt": format_gantt(detail) if detail else {"rows": [], "bars": []},
            },
            "dataset_reports": [
                self._dataset_report(self.base_dir / "data" / "scenario_synthetic_center"),
                self._dataset_report(self.base_dir / "data" / "scenario_synthetic_center_large"),
            ],
            "event_summary": {
                "total": len(events),
                "by_status": dict(event_distribution),
                "open_events": [item for item in events if item["status"] in {"pending", "processing", "failed"}],
            },
        }

    def _dataset_report(self, dataset_dir: Path) -> dict[str, Any]:
        fingerprint = self._dataset_fingerprint(dataset_dir)
        cached = self._dataset_cache.get(str(dataset_dir))
        if cached and cached[0] == fingerprint:
            self._dataset_hits += 1
            return cached[1]

        self._dataset_misses += 1
        manifest = self._read_json(dataset_dir / "dataset_manifest.json")
        orders = self._read_json(dataset_dir / "order_arrivals.json")
        equipment = self._read_json(dataset_dir / "equipment_catalog.json")
        operations = self._read_json(dataset_dir / "operations_constraints.json")
        if isinstance(orders, dict):
            orders = orders.get("orders", [])
        order_types = Counter(order.get("order_type") for order in orders)
        certification_types = Counter(order.get("certification_type") for order in orders)
        route_lengths = [len(order.get("detection_route") or []) for order in orders]
        report = {
            "dataset": dataset_dir.name,
            "version": manifest.get("dataset_version") or manifest.get("version"),
            "simulation_period": manifest.get("simulation_period") or manifest.get("period"),
            "order_count": len(orders),
            "order_type_distribution": dict(order_types),
            "certification_distribution": dict(certification_types),
            "max_route_length": max(route_lengths) if route_lengths else 0,
            "equipment_instance_count": sum(
                len(item.get("instances", []))
                for item in equipment.get("equipment_types", [])
            ),
            "employee_count": len(operations.get("employees", [])),
            "transfer_rule_count": len(operations.get("transfer_rules", [])),
            "maintenance_count": len(operations.get("maintenance_windows", [])),
            "failure_count": len(operations.get("failure_events", operations.get("simulated_failures", []))),
        }
        self._dataset_cache[str(dataset_dir)] = (fingerprint, report)
        return report

    def _read_json(self, path: Path):
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _dataset_fingerprint(self, dataset_dir: Path) -> tuple[float | None, ...]:
        files = [
            dataset_dir / "dataset_manifest.json",
            dataset_dir / "order_arrivals.json",
            dataset_dir / "equipment_catalog.json",
            dataset_dir / "operations_constraints.json",
        ]
        return tuple(path.stat().st_mtime if path.exists() else None for path in files)

    def cache_stats(self) -> dict[str, int]:
        return {
            "dataset_entries": len(self._dataset_cache),
            "dataset_hits": self._dataset_hits,
            "dataset_misses": self._dataset_misses,
        }
