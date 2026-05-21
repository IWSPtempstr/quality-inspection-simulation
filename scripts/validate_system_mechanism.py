from __future__ import annotations

import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _record(checks: list[dict[str, Any]], name: str, condition: bool, evidence: Any = None, error: str | None = None) -> None:
    checks.append(
        {
            "name": name,
            "passed": bool(condition),
            "evidence": evidence,
            "error": error,
        }
    )


def _json_ready(value: Any) -> Any:
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def run_validation(dataset_dir: Path | str, working_dir: Path | str) -> dict[str, Any]:
    dataset_path = Path(dataset_dir).resolve()
    working_path = Path(working_dir).resolve()
    working_path.mkdir(parents=True, exist_ok=True)
    db_path = working_path / "validation.db"
    index_path = working_path / "rag_index"
    if db_path.exists():
        db_path.unlink()
    if index_path.exists():
        shutil.rmtree(index_path)
    checks: list[dict[str, Any]] = []

    orders_path = dataset_path / "orders.json"
    knowledge_dir = dataset_path / "knowledge_base"
    orders_payload = _load_json(orders_path)
    dataset_orders = orders_payload.get("orders", [])
    expectations = orders_payload.get("expectations", {})
    _record(
        checks,
        "dataset_loaded",
        orders_path.exists() and knowledge_dir.exists() and bool(dataset_orders),
        {
            "orders_path": str(orders_path),
            "knowledge_dir": str(knowledge_dir),
            "order_count": len(dataset_orders),
        },
    )

    env_updates = {
        "DATABASE_URL": f"sqlite:///{db_path}",
        "KNOWLEDGE_BASE_DIR": str(knowledge_dir),
        "RAG_INDEX_DIR": str(index_path),
        "EMBEDDING_PROVIDER": "deterministic",
        "EMBEDDING_API_KEY": None,
        "EMBEDDING_BASE_URL": None,
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "MCP_SERVER_COMMAND": os.environ.get("MCP_SERVER_COMMAND", sys.executable),
        "MCP_SERVER_ARGS": "-m mcp_server.simulation_server",
        "MCP_SERVER_CWD": str(PROJECT_ROOT),
    }

    try:
        with _temporary_env(env_updates), _temporary_cwd(PROJECT_ROOT):
            from app import create_app
            from fastapi.testclient import TestClient

            client = TestClient(create_app())

            reindex_response = client.post("/api/knowledge/reindex")
            search_response = client.post(
                "/api/knowledge/search",
                json={"query": "CCC 安全 电磁兼容 设备顺序", "top_k": 2},
            )
            search_results = search_response.json()["data"]
            _record(
                checks,
                "rag_reindex_and_search",
                reindex_response.status_code == 200 and bool(search_results),
                {
                    "reindex_status": reindex_response.status_code,
                    "search_sources": [item["source"] for item in search_results],
                },
            )

            created_order_ids: list[str] = []
            for order in dataset_orders:
                response = client.post("/api/orders", json=order)
                body = response.json()
                created_order_ids.append(body["data"]["id"])
            orders_response = client.get("/api/orders")
            _record(
                checks,
                "order_crud_ingestion",
                orders_response.status_code == 200 or len(created_order_ids) == len(dataset_orders),
                {
                    "created_order_ids": created_order_ids,
                    "order_count": len(created_order_ids),
                },
            )

            queue_response = client.post("/api/queue/rebuild")
            queue_data = queue_response.json()["data"]
            scheduled_orders = queue_data.get("scheduled_orders", [])
            blocked_orders = queue_data.get("blocked_orders", [])
            scheduled_types = [item["order_type"] for item in scheduled_orders]
            vip_order = next((item for item in scheduled_orders if item["order_type"] == "vip"), None)
            urgent_order = next((item for item in scheduled_orders if item["order_type"] == "urgent"), None)
            normal_order = next((item for item in scheduled_orders if item["order_type"] == "normal"), None)
            same_instance_priority_order = None
            equipment_instances_recorded = all(
                step.get("equipment_id")
                for order in scheduled_orders
                for step in order.get("steps", [])
                if step.get("status") == "scheduled"
            )
            if vip_order and normal_order:
                vip_safety_step = next((step for step in vip_order["steps"] if step["equipment_type"] == "safety_tester"), None)
                normal_safety_step = next((step for step in normal_order["steps"] if step["equipment_type"] == "safety_tester"), None)
                if vip_safety_step and normal_safety_step:
                    if vip_safety_step.get("equipment_id") == normal_safety_step.get("equipment_id"):
                        same_instance_priority_order = vip_safety_step["end_minute"] <= normal_safety_step["start_minute"]
                    else:
                        same_instance_priority_order = True
            queue_ok = (
                queue_response.status_code == 200
                and scheduled_types[:3] == expectations.get("scheduled_order_types", ["vip", "urgent", "normal"])
                and len(blocked_orders) == expectations.get("blocked_count", 1)
                and equipment_instances_recorded
                and same_instance_priority_order is True
                and any(step["required_batches"] > 1 for order in scheduled_orders for step in order.get("steps", []))
                and all(
                    step["sequence"] == index + 1
                    for order in scheduled_orders
                    for index, step in enumerate(order.get("steps", []))
                )
            )
            _record(
                checks,
                "queue_rebuild_priority_capacity_sequence",
                queue_ok,
                {
                    "scheduled_order_types": scheduled_types,
                    "blocked_count": len(blocked_orders),
                    "equipment_instances_recorded": equipment_instances_recorded,
                    "same_instance_priority_order": same_instance_priority_order,
                },
            )

            schedules_response = client.get("/api/schedules")
            run_id = queue_data["run_id"]
            schedule_detail_response = client.get(f"/api/schedules/{run_id}")
            schedule_detail = schedule_detail_response.json()["data"]
            schedule_ok = (
                schedules_response.status_code == 200
                and schedule_detail_response.status_code == 200
                and schedules_response.json()["data"]
                and schedules_response.json()["data"][0]["id"] == run_id
                and schedule_detail["id"] == run_id
                and schedule_detail["scheduled_count"] == len(scheduled_orders)
                and schedule_detail["blocked_count"] == len(blocked_orders)
                and len(schedule_detail["steps"]) >= len(scheduled_orders)
            )
            _record(
                checks,
                "schedule_persistence",
                schedule_ok,
                {
                    "run_id": run_id,
                    "step_count": len(schedule_detail["steps"]),
                },
            )

            agent_response = client.post("/api/agent/run", json={"task_type": "query_queue", "payload": {}})
            agent_data = agent_response.json()["data"]
            mcp_response = client.get("/api/mcp/status")
            agent_ok = (
                agent_response.status_code == 200
                and mcp_response.status_code == 200
                and "orchestrator" in agent_data["visited_agents"]
                and "queue_scheduler" in agent_data["visited_agents"]
                and "equipment_monitor" in agent_data["visited_agents"]
                and agent_data["handoffs"]
                and _json_ready(agent_data["result"]).get("equipment_status")
            )
            _record(
                checks,
                "agent_handoff_and_mcp_monitoring",
                agent_ok,
                {
                    "visited_agents": agent_data.get("visited_agents", []),
                    "handoffs": agent_data.get("handoffs", []),
                    "mcp_status": mcp_response.json()["data"],
                },
            )
    except Exception as exc:  # noqa: BLE001 - validation should return structured failure evidence
        _record(checks, "runtime_exception", False, error=str(exc))

    passed = sum(1 for check in checks if check["passed"])
    failed = sum(1 for check in checks if not check["passed"])
    return {
        "dataset": str(dataset_path),
        "working_dir": str(working_path),
        "summary": {
            "passed": passed,
            "failed": failed,
        },
        "checks": checks,
    }


def main() -> None:
    dataset_dir = PROJECT_ROOT / "data" / "mechanism_validation"
    working_dir = PROJECT_ROOT / "data" / "_validation_tmp"
    report = run_validation(dataset_dir, working_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["summary"]["failed"] else 0)


if __name__ == "__main__":
    main()
