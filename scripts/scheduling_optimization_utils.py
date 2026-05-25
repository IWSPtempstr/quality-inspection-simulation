from __future__ import annotations

import json
import math
import shutil
import time
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
SCENARIO_CONFIG = {
    "balanced": {
        "label": "normal_load",
        "target_range": (0.60, 0.75),
        "equipment_instances": {
            "safety_tester": 5,
            "emc_tester": 13,
            "performance_bench": 4,
            "environmental_chamber": 18,
            "international_protocol_bench": 2,
        },
        "sla_buffer_days": {"vip": 3, "urgent": 5, "normal": 12},
    },
    "highload": {
        "label": "high_load",
        "target_range": (0.80, 0.95),
        "equipment_instances": {
            "safety_tester": 4,
            "emc_tester": 10,
            "performance_bench": 4,
            "environmental_chamber": 14,
            "international_protocol_bench": 1,
        },
        "sla_buffer_days": {"vip": 2, "urgent": 4, "normal": 9},
    },
}


def capacity_report_for_dataset(dataset_dir: Path | str, effective_hours_per_workday: int = 8) -> dict[str, Any]:
    dataset_path = Path(dataset_dir)
    equipment_catalog = _read_json(dataset_path / "equipment_catalog.json")
    orders = _read_json(dataset_path / "order_arrivals.json").get("orders", [])
    config = _read_json(dataset_path / "generation_config.json")
    if not orders:
        return {
            "dataset": dataset_path.name,
            "scenario_label": "empty",
            "order_count": 0,
            "average_load_factor": 0.0,
            "equipment": {},
        }

    start = min(_parse_dt(order["arrival_time"]) for order in orders)
    end = max(_parse_dt(order["arrival_time"]) for order in orders)
    workdays = _workday_count(start.date(), end.date())
    demand_hours = Counter()
    step_counts = Counter()
    for order in orders:
        for step in order.get("detection_route") or []:
            equipment_type = step.get("equipment_type")
            demand_hours[equipment_type] += float(step.get("duration_minutes", 0)) / 60
            step_counts[equipment_type] += 1

    equipment_report: dict[str, Any] = {}
    for item in equipment_catalog.get("equipment_types", []):
        equipment_type = item["equipment_type"]
        instances = int(item.get("d", len(item.get("instances", []))) or 0)
        capacity_hours = max(1, workdays * effective_hours_per_workday * instances)
        load_factor = demand_hours[equipment_type] / capacity_hours
        recommended = max(1, math.ceil(demand_hours[equipment_type] / max(1, workdays * effective_hours_per_workday * 0.9)))
        equipment_report[equipment_type] = {
            "instances": instances,
            "demand_hours": round(demand_hours[equipment_type], 2),
            "capacity_hours": round(capacity_hours, 2),
            "load_factor": round(load_factor, 4),
            "step_count": step_counts[equipment_type],
            "recommended_instances_for_90pct": recommended,
        }

    average_load = mean(item["load_factor"] for item in equipment_report.values()) if equipment_report else 0.0
    label = config.get("scenario_label") or _scenario_label(average_load, equipment_report)
    return {
        "dataset": dataset_path.name,
        "scenario_label": label,
        "order_count": len(orders),
        "period": {"start": start.isoformat(), "end": end.isoformat(), "workdays": workdays},
        "effective_hours_per_workday": effective_hours_per_workday,
        "average_load_factor": round(average_load, 4),
        "equipment": equipment_report,
    }


def derive_optimized_dataset(source_dir: Path | str, output_dir: Path | str, scenario: str) -> dict[str, Any]:
    if scenario not in SCENARIO_CONFIG:
        raise ValueError(f"unknown scenario: {scenario}")
    source_path = Path(source_dir)
    output_path = Path(output_dir)
    if output_path.exists():
        shutil.rmtree(output_path)
    shutil.copytree(source_path, output_path)

    scenario_config = SCENARIO_CONFIG[scenario]
    equipment_catalog = _read_json(output_path / "equipment_catalog.json")
    operations = _read_json(output_path / "operations_constraints.json")
    orders_payload = _read_json(output_path / "order_arrivals.json")
    config = _read_json(output_path / "generation_config.json")

    _scale_equipment_catalog(equipment_catalog, scenario_config["equipment_instances"])
    _scale_operations(operations, scenario_config["equipment_instances"])
    _apply_dynamic_sla(orders_payload["orders"], scenario_config["sla_buffer_days"])
    config["scenario_label"] = scenario_config["label"]
    config["capacity_target_range"] = list(scenario_config["target_range"])
    config["dynamic_sla"] = {
        "enabled": True,
        "formula": "arrival_time + ceil(route_duration_hours/8) workdays + order_type_buffer_days",
        "buffer_days": scenario_config["sla_buffer_days"],
    }
    config["dataset_version"] = f"{config.get('dataset_version', '0.4.0')}-{scenario}"

    _write_json(output_path / "equipment_catalog.json", equipment_catalog)
    _write_json(output_path / "operations_constraints.json", operations)
    _write_json(output_path / "order_arrivals.json", orders_payload)
    _write_json(output_path / "generation_config.json", config)
    _write_readme(output_path / "README.md", scenario_config["label"], scenario_config["target_range"])
    _write_manifest(output_path, config, len(orders_payload["orders"]))
    capacity = capacity_report_for_dataset(output_path)
    return {
        "dataset_dir": str(output_path.resolve()),
        "scenario_label": scenario_config["label"],
        "order_count": len(orders_payload["orders"]),
        "dynamic_sla": config["dynamic_sla"],
        "capacity_report": capacity,
    }


def evaluate_dataset(
    dataset_dir: Path | str,
    *,
    integration_order_limit: int = 500,
    sample_mode: str = "spread",
    strategies: list[str] | None = None,
) -> dict[str, Any]:
    from app import create_app
    from fastapi.testclient import TestClient

    dataset_path = Path(dataset_dir).resolve()
    strategies = strategies or ["priority_fifo", "sla_guarded_hybrid"]
    working_dir = PROJECT_ROOT / "data" / "_optimized_scheduling_eval_tmp" / dataset_path.name
    working_dir.mkdir(parents=True, exist_ok=True)
    db_path = working_dir / "evaluation.db"
    index_path = working_dir / "rag_index"
    if db_path.exists():
        db_path.unlink()
    if index_path.exists():
        shutil.rmtree(index_path)

    all_orders = _read_json(dataset_path / "order_arrivals.json")["orders"]
    orders = _sample_orders(all_orders, integration_order_limit, sample_mode)
    env_updates = {
        "DATABASE_URL": f"sqlite:///{db_path}",
        "EQUIPMENT_CATALOG_PATH": str(dataset_path / "equipment_catalog.json"),
        "OPERATIONS_CONSTRAINTS_PATH": str(dataset_path / "operations_constraints.json"),
        "KNOWLEDGE_BASE_DIR": str(dataset_path / "knowledge_base"),
        "RAG_INDEX_DIR": str(index_path),
        "EMBEDDING_PROVIDER": "deterministic",
        "EMBEDDING_API_KEY": None,
        "EMBEDDING_BASE_URL": None,
        "SCHEDULER_HEARTBEAT_ENABLED": "false",
    }
    with _temporary_env(env_updates), _temporary_cwd(PROJECT_ROOT):
        client = TestClient(create_app())
        client.post("/api/knowledge/reindex")
        created = _import_orders(client, orders)
        strategy_results = {}
        latencies = []
        for strategy in strategies:
            started = time.perf_counter()
            response = client.post(f"/api/queue/rebuild?strategy={strategy}")
            latency_ms = int((time.perf_counter() - started) * 1000)
            latencies.append(latency_ms)
            data = response.json()["data"] if response.status_code == 200 else {}
            strategy_results[strategy] = {
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "metrics": data.get("metrics", {}),
            }
        agent_response = client.post("/api/agent/run", json={"task_type": "query_queue", "payload": {}})

    selected = _best_strategy(strategy_results)
    capacity = capacity_report_for_dataset(dataset_path)
    bottleneck_resources = [
        {"equipment_type": key, **value}
        for key, value in capacity["equipment"].items()
        if value["load_factor"] > 0.9
    ]
    baseline = strategy_results.get("priority_fifo", {}).get("metrics", {})
    optimized = strategy_results.get("sla_guarded_hybrid", {}).get("metrics", {})
    return {
        "dataset": dataset_path.name,
        "scenario_label": capacity["scenario_label"],
        "created_orders": created,
        "integration_order_limit": integration_order_limit,
        "sample_mode": sample_mode,
        "selected_strategy": selected,
        "strategy_results": strategy_results,
        "capacity_report": capacity,
        "bottleneck_resources": bottleneck_resources,
        "comparison": {
            "sla_on_time_rate_delta": round(float(optimized.get("on_time_rate", 0)) - float(baseline.get("on_time_rate", 0)), 4),
            "total_delay_reduction_ratio": _reduction_ratio(baseline.get("total_delay_minutes", 0), optimized.get("total_delay_minutes", 0)),
            "rebuild_latency_avg_ms": round(mean(latencies), 2) if latencies else 0,
            "rebuild_latency_p95_ms": _p95(latencies),
        },
        "agent_handoff": {
            "status_code": agent_response.status_code,
            "visited_agents": agent_response.json().get("data", {}).get("visited_agents", []) if agent_response.status_code == 200 else [],
            "handoffs": agent_response.json().get("data", {}).get("handoffs", []) if agent_response.status_code == 200 else [],
        },
    }


def _scale_equipment_catalog(equipment_catalog: dict[str, Any], target_counts: dict[str, int]) -> None:
    for item in equipment_catalog.get("equipment_types", []):
        equipment_type = item["equipment_type"]
        target = target_counts.get(equipment_type, int(item.get("d", 1)))
        item["d"] = target
        item["instances"] = [
            {
                "equipment_id": f"{equipment_type}-{index}",
                "equipment_type": equipment_type,
                "status": "idle",
                "capacity_n": int(item.get("capacity_n", 1)),
                "lab_area": item.get("lab_area", "lab"),
                "maintenance_group": item.get("maintenance_group"),
            }
            for index in range(1, target + 1)
        ]


def _scale_operations(operations: dict[str, Any], target_counts: dict[str, int]) -> None:
    multipliers = {
        "emc_tester": ("emc_engineer", "emc_lab", "emc_check", "emp-emc", 1),
        "environmental_chamber": ("environmental_engineer", "environmental_lab", "environmental_check", "emp-environment", 3),
        "performance_bench": ("performance_engineer", "performance_lab", "performance_check", "emp-performance", 2),
        "safety_tester": ("safety_engineer", "safety_lab", "safety_check", "emp-safety", 2),
        "international_protocol_bench": ("certification_reviewer", "review_lab", "cb_review", "emp-review", 1),
    }
    employees = operations.get("employees", [])
    by_prefix = {prefix: [item for item in employees if item.get("employee_id", "").startswith(prefix)] for *_, prefix, _ in multipliers.values()}
    for equipment_type, (role, lab_area, skill, prefix, parallel) in multipliers.items():
        target = max(1, target_counts.get(equipment_type, 1))
        desired_staff = max(2, math.ceil(target / max(1, parallel)))
        existing = by_prefix.get(prefix, [])
        for index in range(len(existing) + 1, desired_staff + 1):
            employees.append(
                {
                    "employee_id": f"{prefix}-{index}",
                    "name": f"{role}-{index}",
                    "roles": [role],
                    "skills": [skill, equipment_type],
                    "lab_areas": [lab_area],
                    "shift_id": "lab_day",
                    "max_parallel_assignments": parallel,
                }
            )
    desired_assistants = max(4, target_counts.get("emc_tester", 1) * 2)
    existing_assistants = [item for item in employees if item.get("employee_id", "").startswith("emp-assistant")]
    for index in range(len(existing_assistants) + 1, desired_assistants + 1):
        employees.append(
            {
                "employee_id": f"emp-assistant-{index}",
                "name": f"助理操作员{index}",
                "roles": ["assistant_operator"],
                "skills": ["emc_check", "performance_check", "environmental_check"],
                "lab_areas": ["emc_lab", "performance_lab", "environmental_lab"],
                "shift_id": "lab_day",
                "max_parallel_assignments": 1,
            }
        )
    desired_prep = max(4, math.ceil(sum(target_counts.values()) / 4))
    desired_transfer = max(4, math.ceil(sum(target_counts.values()) / 5))
    _scale_employee_pool(
        employees,
        prefix="emp-prep",
        desired_count=desired_prep,
        template={
            "roles": ["sample_operator"],
            "skills": ["preprocessing"],
            "lab_areas": ["intake"],
            "shift_id": "intake_morning",
            "max_parallel_assignments": 1,
        },
    )
    _scale_employee_pool(
        employees,
        prefix="emp-transfer",
        desired_count=desired_transfer,
        template={
            "roles": ["transfer_operator"],
            "skills": ["sample_transfer"],
            "lab_areas": ["intake", "safety_lab", "emc_lab", "performance_lab", "environmental_lab", "review_lab"],
            "shift_id": "lab_day",
            "max_parallel_assignments": 1,
        },
    )
    operations["preprocessing_resources"] = [
        {"resource_id": f"prep-{index}", "resource_type": "prep_station"}
        for index in range(1, desired_prep + 1)
    ]
    operations["transfer_resources"] = [
        {"resource_id": f"cart-{index}", "resource_type": "transfer_cart"}
        for index in range(1, desired_transfer + 1)
    ]
    operations["employees"] = employees


def _scale_employee_pool(employees: list[dict[str, Any]], prefix: str, desired_count: int, template: dict[str, Any]) -> None:
    existing = [item for item in employees if item.get("employee_id", "").startswith(prefix)]
    for index in range(len(existing) + 1, desired_count + 1):
        employees.append(
            {
                "employee_id": f"{prefix}-{index}",
                "name": f"{prefix}-{index}",
                **template,
            }
        )


def _apply_dynamic_sla(orders: list[dict[str, Any]], buffer_days: dict[str, int]) -> None:
    for order in orders:
        arrival = _parse_dt(order["arrival_time"])
        duration_minutes = sum(int(step.get("duration_minutes", 0)) + int(step.get("setup_minutes", 0) or 0) for step in order.get("detection_route", []))
        theoretical_days = max(1, math.ceil(duration_minutes / (8 * 60)))
        promised_days = theoretical_days + int(buffer_days[order["order_type"]])
        order["promised_finish_time"] = _add_working_days(arrival, promised_days).isoformat()


def _import_orders(client, orders: list[dict[str, Any]]) -> int:
    created = 0
    for order in orders:
        payload = {
            "order_type": order["order_type"],
            "sample_name": order["sample_name"],
            "sample_quantity": order["sample_quantity"],
            "certification_type": order["certification_type"],
            "requested_projects": order.get("requested_projects", []),
            "detection_route": order.get("detection_route", []),
            "preprocessing_profile": order.get("preprocessing_profile"),
            "sample_storage_class": order.get("sample_storage_class"),
            "transfer_requirements": order.get("transfer_requirements", {}),
            "arrival_time": order.get("arrival_time"),
            "promised_finish_time": order.get("promised_finish_time"),
        }
        response = client.post("/api/orders", json=payload)
        if response.status_code == 201:
            created += 1
    return created


def _sample_orders(orders: list[dict[str, Any]], limit: int, sample_mode: str) -> list[dict[str, Any]]:
    if sample_mode == "head":
        return list(orders[:limit])
    return _sample_across_period(orders, limit)


def _sample_across_period(orders: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or len(orders) <= limit:
        return list(orders)
    if limit == 1:
        return [orders[0]]
    step = (len(orders) - 1) / (limit - 1)
    return [orders[round(index * step)] for index in range(limit)]


def _best_strategy(strategy_results: dict[str, Any]) -> str | None:
    if not strategy_results:
        return None
    return max(
        strategy_results,
        key=lambda strategy: (
            float(strategy_results[strategy].get("metrics", {}).get("on_time_rate", 0)),
            float(strategy_results[strategy].get("metrics", {}).get("vip_sla_rate", 0)),
            -float(strategy_results[strategy].get("metrics", {}).get("total_delay_minutes", 0)),
        ),
    )


def _scenario_label(average_load: float, equipment_report: dict[str, Any]) -> str:
    if any(item["load_factor"] > 1.0 for item in equipment_report.values()):
        return "stress_load"
    if average_load >= 0.80:
        return "high_load"
    return "normal_load"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_dt(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _workday_count(start: date, end: date) -> int:
    return sum(1 for offset in range((end - start).days + 1) if (start + timedelta(days=offset)).weekday() < 5)


def _add_working_days(arrival: datetime, days: int) -> datetime:
    current = arrival.date()
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return datetime.combine(current, dt_time(18, 0), tzinfo=arrival.tzinfo or TZ)


def _reduction_ratio(baseline: Any, optimized: Any) -> float:
    baseline_value = float(baseline or 0)
    optimized_value = float(optimized or 0)
    if baseline_value <= 0:
        return 0.0
    return round((baseline_value - optimized_value) / baseline_value, 4)


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _write_readme(path: Path, scenario_label: str, target_range: tuple[float, float]) -> None:
    content = f"""# 合成拟真检测中心优化数据集

该目录由 5000 单压力数据集派生，仍为合成仿真数据，不代表真实检测中心参数。

- 场景标签：`{scenario_label}`
- 目标设备平均负载：`{target_range[0]:.0%}-{target_range[1]:.0%}`
- SLA：按订单检测路线理论工时和订单类型缓冲动态生成
"""
    path.write_text(content, encoding="utf-8")


def _write_manifest(output_path: Path, config: dict[str, Any], order_count: int) -> None:
    manifest = {
        "dataset_name": output_path.name,
        "dataset_version": config["dataset_version"],
        "scenario_label": config["scenario_label"],
        "synthetic": True,
        "seed": config["seed"],
        "period": config["period"],
        "order_count": order_count,
        "usage_boundary": "合成数据，仅用于正常/高负载调度机制验证，不代表真实机构参数。",
    }
    _write_json(output_path / "dataset_manifest.json", manifest)


@contextmanager
def _temporary_env(updates: dict[str, str | None]) -> Iterator[None]:
    import os

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
    import os

    current = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(current)
