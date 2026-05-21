from __future__ import annotations

import json
import os
import shutil
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATASET_DIR = PROJECT_ROOT / "data" / "scenario_synthetic_center"

REQUIRED_FILES = [
    "dataset_manifest.json",
    "generation_config.json",
    "equipment_catalog.json",
    "project_catalog.json",
    "order_arrivals.json",
    "priority_rules.json",
    "operations_constraints.json",
    "README.md",
    "knowledge_base/certification_flows.md",
    "knowledge_base/equipment_constraints.md",
    "knowledge_base/priority_rules.md",
    "knowledge_base/operations_constraints.md",
]


@contextmanager
def _temporary_env(updates: dict[str, str | None]) -> Iterator[None]:
    previous: dict[str, str | None] = {}
    try:
        for key, value in updates.items():
            previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _temporary_cwd(path: Path) -> Iterator[None]:
    current = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(current)


def validate_dataset(
    dataset_dir: Path | str = DATASET_DIR,
    working_dir: Path | str | None = None,
    integration_order_limit: int | None = None,
) -> dict[str, Any]:
    dataset_path = Path(dataset_dir).resolve()
    working_path = Path(working_dir).resolve() if working_dir else PROJECT_ROOT / "data" / "_synthetic_validation_tmp"
    working_path.mkdir(parents=True, exist_ok=True)
    db_path = working_path / "synthetic_validation.db"
    index_path = working_path / "rag_index"
    if db_path.exists():
        db_path.unlink()
    if index_path.exists():
        shutil.rmtree(index_path)

    checks: list[dict[str, Any]] = []
    try:
        missing = [item for item in REQUIRED_FILES if not (dataset_path / item).exists()]
        _record(checks, "required_files", not missing, {"missing": missing, "required_count": len(REQUIRED_FILES)})
        if missing:
            return _summary(dataset_path, working_path, checks)

        config = _read_json(dataset_path / "generation_config.json")
        equipment_catalog = _read_json(dataset_path / "equipment_catalog.json")
        project_catalog = _read_json(dataset_path / "project_catalog.json")
        order_arrivals = _read_json(dataset_path / "order_arrivals.json")
        operations = _read_json(dataset_path / "operations_constraints.json")
        priority_rules = _read_json(dataset_path / "priority_rules.json")

        orders = order_arrivals["orders"]
        target_range = config["target_order_range"]
        _record(
            checks,
            "order_volume",
            target_range["min"] <= len(orders) <= target_range["max"],
            {"order_count": len(orders), "target_range": target_range},
        )

        _record(checks, "distribution_ranges", _distribution_ok(orders), _distribution_evidence(orders))
        _record(
            checks,
            "catalog_references",
            _catalog_references_ok(equipment_catalog, project_catalog, orders),
            _catalog_reference_evidence(equipment_catalog, project_catalog, orders),
        )
        _record(
            checks,
            "operations_constraints",
            _operations_ok(config, equipment_catalog, operations),
            _operations_evidence(operations),
        )
        _record(
            checks,
            "priority_rules",
            priority_rules.get("priority_order") == ["vip", "urgent", "normal"] and priority_rules.get("preemption") is False,
            {"priority_order": priority_rules.get("priority_order"), "preemption": priority_rules.get("preemption")},
        )
        _record(
            checks,
            "rag_knowledge",
            _rag_knowledge_ok(dataset_path / "knowledge_base"),
            {"knowledge_files": sorted(path.name for path in (dataset_path / "knowledge_base").glob("*"))},
        )
        integration_orders = orders[:integration_order_limit] if integration_order_limit else orders
        _run_integration_checks(
            dataset_path,
            working_path,
            db_path,
            index_path,
            integration_orders,
            checks,
            integration_order_limit=integration_order_limit,
        )
    except Exception as exc:  # noqa: BLE001 - validator returns structured evidence
        _record(checks, "runtime_exception", False, error=str(exc))

    return _summary(dataset_path, working_path, checks)


def _run_integration_checks(
    dataset_path: Path,
    working_path: Path,
    db_path: Path,
    index_path: Path,
    orders: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    integration_order_limit: int | None = None,
) -> None:
    env_updates = {
        "DATABASE_URL": f"sqlite:///{db_path}",
        "KNOWLEDGE_BASE_DIR": str(dataset_path / "knowledge_base"),
        "RAG_INDEX_DIR": str(index_path),
        "EMBEDDING_PROVIDER": "deterministic",
        "EMBEDDING_API_KEY": None,
        "EMBEDDING_BASE_URL": None,
        "MCP_SERVER_COMMAND": os.environ.get("MCP_SERVER_COMMAND", sys.executable),
        "MCP_SERVER_ARGS": "-m mcp_server.simulation_server",
        "MCP_SERVER_CWD": str(PROJECT_ROOT),
    }
    with _temporary_env(env_updates), _temporary_cwd(PROJECT_ROOT):
        from app import create_app
        from fastapi.testclient import TestClient

        client = TestClient(create_app())
        reindex_response = client.post("/api/knowledge/reindex")
        search_response = client.post("/api/knowledge/search", json={"query": "VIP 加急 非抢占 设备 维护", "top_k": 3})
        created = 0
        for order in orders:
            payload = {
                "order_type": order["order_type"],
                "sample_name": order["sample_name"],
                "sample_quantity": order["sample_quantity"],
                "certification_type": order["certification_type"],
                "requested_projects": order.get("requested_projects", []),
                "arrival_time": order.get("arrival_time"),
                "promised_finish_time": order.get("promised_finish_time"),
            }
            response = client.post("/api/orders", json=payload)
            if response.status_code == 201:
                created += 1
        queue_response = client.post("/api/queue/rebuild")
        queue_data = queue_response.json()["data"] if queue_response.status_code == 200 else {}
        scheduled_orders = queue_data.get("scheduled_orders", [])
        schedules_response = client.get("/api/schedules")
        batch_step_seen = any(
            step.get("required_batches", 0) > 1
            for scheduled in scheduled_orders
            for step in scheduled.get("steps", [])
        )
        priority_seen = [item["order_type"] for item in scheduled_orders[: min(20, len(scheduled_orders))]]
        arrival_respected = all(
            not scheduled.get("steps")
            or datetime.fromisoformat(scheduled["steps"][0]["start_time"]) >= datetime.fromisoformat(scheduled["arrival_time"])
            for scheduled in scheduled_orders
        )
        workday_window_respected = all(
            _step_within_workday(step)
            for scheduled in scheduled_orders
            for step in scheduled.get("steps", [])
        )
        queue_ok = (
            created == len(orders)
            and reindex_response.status_code == 200
            and search_response.status_code == 200
            and queue_response.status_code == 200
            and schedules_response.status_code == 200
            and scheduled_orders
            and arrival_respected
            and workday_window_respected
            and batch_step_seen
        )
        _record(
            checks,
            "api_queue_integration",
            queue_ok,
            {
                "created_orders": created,
                "scheduled_orders": len(scheduled_orders),
                "integration_order_limit": integration_order_limit,
                "first_order_types": priority_seen[:10],
                "arrival_respected": arrival_respected,
                "workday_window_respected": workday_window_respected,
                "batch_step_seen": batch_step_seen,
                "knowledge_hits": len(search_response.json().get("data", [])) if search_response.status_code == 200 else 0,
                "metrics": queue_data.get("metrics", {}),
            },
        )
        agent_response = client.post("/api/agent/run", json={"task_type": "query_queue", "payload": {}})
        agent_data = agent_response.json()["data"] if agent_response.status_code == 200 else {}
        _record(
            checks,
            "agent_handoff",
            agent_response.status_code == 200
            and "orchestrator" in agent_data.get("visited_agents", [])
            and "queue_scheduler" in agent_data.get("visited_agents", [])
            and "equipment_monitor" in agent_data.get("visited_agents", [])
            and bool(agent_data.get("handoffs")),
            {
                "visited_agents": agent_data.get("visited_agents", []),
                "handoffs": agent_data.get("handoffs", []),
            },
        )


def _distribution_ok(orders: list[dict[str, Any]]) -> bool:
    evidence = _distribution_evidence(orders)
    order_distribution = evidence["order_type_distribution"]
    cert_distribution = evidence["certification_distribution"]
    return (
        0.70 <= order_distribution.get("normal", 0) <= 0.80
        and 0.14 <= order_distribution.get("urgent", 0) <= 0.22
        and 0.04 <= order_distribution.get("vip", 0) <= 0.10
        and 0.40 <= cert_distribution.get("ccc", 0) <= 0.50
        and 0.30 <= cert_distribution.get("cvc", 0) <= 0.40
        and 0.15 <= cert_distribution.get("international", 0) <= 0.25
        and evidence["bulk_order_count"] > 0
    )


def _distribution_evidence(orders: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(orders) or 1
    order_types = Counter(order["order_type"] for order in orders)
    certs = Counter(order["certification_type"] for order in orders)
    return {
        "order_type_distribution": {key: round(value / total, 4) for key, value in order_types.items()},
        "certification_distribution": {key: round(value / total, 4) for key, value in certs.items()},
        "bulk_order_count": sum(1 for order in orders if order["sample_quantity"] >= 5),
    }


def _step_within_workday(step: dict[str, Any]) -> bool:
    start = datetime.fromisoformat(step["start_time"])
    end = datetime.fromisoformat(step["end_time"])
    if start.weekday() >= 5 or end.weekday() >= 5:
        return False
    return 9 <= start.hour < 18 and (end.hour < 18 or (end.hour == 18 and end.minute == 0 and end.second == 0))


def _catalog_references_ok(equipment_catalog: dict[str, Any], project_catalog: dict[str, Any], orders: list[dict[str, Any]]) -> bool:
    evidence = _catalog_reference_evidence(equipment_catalog, project_catalog, orders)
    return not evidence["missing_equipment_types"] and not evidence["missing_requested_projects"] and evidence["positive_capacity"] and evidence["positive_durations"] and evidence["valid_d_counts"]


def _catalog_reference_evidence(equipment_catalog: dict[str, Any], project_catalog: dict[str, Any], orders: list[dict[str, Any]]) -> dict[str, Any]:
    equipment_types = {item["equipment_type"] for item in equipment_catalog["equipment_types"]}
    known_projects: set[str] = set()
    project_equipment_types: set[str] = set()
    positive_durations = True
    for flow in project_catalog["certification_flows"]:
        for step in flow["steps"]:
            known_projects.add(step["project_id"])
            project_equipment_types.add(step["equipment_type"])
            positive_durations = positive_durations and min(step["t_min"], step["t_mode"], step["t_max"]) > 0
    requested = {project for order in orders for project in order.get("requested_projects", [])}
    return {
        "missing_equipment_types": sorted(project_equipment_types - equipment_types),
        "missing_requested_projects": sorted(requested - known_projects),
        "positive_capacity": all(item["capacity_n"] > 0 for item in equipment_catalog["equipment_types"]),
        "valid_d_counts": all(item["d"] == len(item["instances"]) and item["d"] > 0 for item in equipment_catalog["equipment_types"]),
        "positive_durations": positive_durations,
    }


def _operations_ok(config: dict[str, Any], equipment_catalog: dict[str, Any], operations: dict[str, Any]) -> bool:
    period_start = date.fromisoformat(config["period"]["start_date"])
    period_end = date.fromisoformat(config["period"]["end_date"])
    equipment_ids = {
        instance["equipment_id"]
        for item in equipment_catalog["equipment_types"]
        for instance in item["instances"]
    }
    events = [*operations.get("maintenance_windows", []), *operations.get("failure_events", [])]
    return (
        bool(operations.get("shifts"))
        and bool(operations.get("staff_roles"))
        and all(role["staff_count"] > 0 for role in operations["staff_roles"])
        and all(
            event["equipment_id"] in equipment_ids
            and period_start <= datetime.fromisoformat(event["start"]).date() <= period_end
            and period_start <= datetime.fromisoformat(event["end"]).date() <= period_end
            and datetime.fromisoformat(event["start"]) < datetime.fromisoformat(event["end"])
            for event in events
        )
    )


def _operations_evidence(operations: dict[str, Any]) -> dict[str, Any]:
    return {
        "shift_count": len(operations.get("shifts", [])),
        "staff_role_count": len(operations.get("staff_roles", [])),
        "maintenance_count": len(operations.get("maintenance_windows", [])),
        "failure_count": len(operations.get("failure_events", [])),
    }


def _rag_knowledge_ok(knowledge_dir: Path) -> bool:
    files = list(knowledge_dir.glob("*.md"))
    return len(files) >= 4 and all(path.read_text(encoding="utf-8").strip() for path in files)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _record(checks: list[dict[str, Any]], name: str, condition: bool, evidence: Any = None, error: str | None = None) -> None:
    checks.append({"name": name, "passed": bool(condition), "evidence": evidence, "error": error})


def _summary(dataset_path: Path, working_path: Path, checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "dataset": str(dataset_path),
        "working_dir": str(working_path),
        "summary": {
            "passed": sum(1 for check in checks if check["passed"]),
            "failed": sum(1 for check in checks if not check["passed"]),
        },
        "checks": checks,
    }


def main() -> None:
    report = validate_dataset(DATASET_DIR)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["summary"]["failed"] else 0)


if __name__ == "__main__":
    main()
