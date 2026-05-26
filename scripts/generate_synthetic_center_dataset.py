from __future__ import annotations

import hashlib
import json
import random
import sys
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATASET_DIR = PROJECT_ROOT / "data" / "scenario_synthetic_center"
TZ = timezone(timedelta(hours=8))


DEFAULT_CONFIG: dict[str, Any] = {
    "dataset_version": "0.4.0",
    "seed": 20260521,
    "timezone": "Asia/Shanghai",
    "period": {
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
    },
    "target_order_count": 500,
    "target_order_range": {
        "min": 480,
        "max": 520,
    },
    "arrival_windows": [
        {"name": "morning_peak", "start": "09:00", "end": "11:00", "lambda_per_hour": 5.2},
        {"name": "afternoon_peak", "start": "13:00", "end": "16:00", "lambda_per_hour": 3.1},
        {"name": "late_window", "start": "16:00", "end": "18:00", "lambda_per_hour": 1.8},
    ],
    "order_type_distribution": {
        "normal": 0.75,
        "urgent": 0.18,
        "vip": 0.07,
    },
    "certification_distribution": {
        "ccc": 0.45,
        "cvc": 0.35,
        "international": 0.20,
    },
    "sla_working_days": {
        "normal": 7,
        "urgent": 3,
        "vip": 2,
    },
}

LARGE_CONFIG: dict[str, Any] = {
    **deepcopy(DEFAULT_CONFIG),
    "dataset_version": "0.4.0-large",
    "seed": 20260522,
    "period": {
        "start_date": "2026-06-01",
        "end_date": "2026-11-30",
    },
    "target_order_count": 5000,
    "target_order_range": {
        "min": 4950,
        "max": 5050,
    },
    "arrival_windows": [
        {"name": "morning_peak", "start": "09:00", "end": "11:00", "lambda_per_hour": 12.5},
        {"name": "afternoon_peak", "start": "13:00", "end": "16:00", "lambda_per_hour": 8.5},
        {"name": "late_window", "start": "16:00", "end": "18:00", "lambda_per_hour": 4.5},
    ],
}


def generate_dataset(dataset_dir: Path | str = DATASET_DIR, config: dict[str, Any] | None = None) -> dict[str, Any]:
    output_dir = Path(dataset_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "generation_config.json"
    config = deepcopy(config) if config is not None else (_read_json(config_path) if config_path.exists() else deepcopy(DEFAULT_CONFIG))

    equipment_catalog = _build_equipment_catalog()
    project_catalog = _build_project_catalog()
    priority_rules = _build_priority_rules()
    operations_constraints = _build_operations_constraints()
    order_arrivals = _build_order_arrivals(config, project_catalog)
    lifecycle_events = _build_order_lifecycle_events(config, order_arrivals)

    _write_json(config_path, config)
    _write_json(output_dir / "equipment_catalog.json", equipment_catalog)
    _write_json(output_dir / "project_catalog.json", project_catalog)
    _write_json(output_dir / "priority_rules.json", priority_rules)
    _write_json(output_dir / "operations_constraints.json", operations_constraints)
    _write_json(output_dir / "order_arrivals.json", order_arrivals)
    _write_json(output_dir / "order_lifecycle_events.json", lifecycle_events)
    _write_knowledge_base(output_dir / "knowledge_base")
    _write_readme(output_dir / "README.md", config)
    manifest = _build_manifest(output_dir, config, order_arrivals)
    _write_json(output_dir / "dataset_manifest.json", manifest)

    return {
        "dataset_dir": str(output_dir.resolve()),
        "seed": config["seed"],
        "order_count": len(order_arrivals["orders"]),
        "files": manifest["files"],
    }


def _build_equipment_catalog() -> dict[str, Any]:
    definitions = [
        {
            "equipment_type": "safety_tester",
            "display_name": "安全性能测试台",
            "d": 4,
            "capacity_n": 3,
            "lab_area": "safety_lab",
            "supported_project_types": ["safety_check"],
            "maintenance_group": "electrical_safety",
        },
        {
            "equipment_type": "emc_tester",
            "display_name": "电磁兼容测试系统",
            "d": 2,
            "capacity_n": 1,
            "lab_area": "emc_lab",
            "supported_project_types": ["emc_check"],
            "maintenance_group": "emc",
        },
        {
            "equipment_type": "performance_bench",
            "display_name": "性能测试台",
            "d": 3,
            "capacity_n": 4,
            "lab_area": "performance_lab",
            "supported_project_types": ["performance_check"],
            "maintenance_group": "performance",
        },
        {
            "equipment_type": "environmental_chamber",
            "display_name": "环境试验箱",
            "d": 2,
            "capacity_n": 6,
            "lab_area": "environmental_lab",
            "supported_project_types": ["environmental_check"],
            "maintenance_group": "environmental",
        },
        {
            "equipment_type": "international_protocol_bench",
            "display_name": "国际认证资料评审台",
            "d": 1,
            "capacity_n": 2,
            "lab_area": "review_lab",
            "supported_project_types": ["cb_review"],
            "maintenance_group": "certification_review",
        },
    ]
    for definition in definitions:
        definition["instances"] = [
            {
                "equipment_id": f"{definition['equipment_type']}-{index}",
                "equipment_type": definition["equipment_type"],
                "status": "idle",
                "capacity_n": definition["capacity_n"],
                "lab_area": definition["lab_area"],
                "maintenance_group": definition["maintenance_group"],
                "performance_factor": round(0.88 + ((index - 1) % 3) * 0.12, 2),
                "calibration_status": "valid" if index % 4 else "due_soon",
                "failure_rate": round(0.005 + (index % 3) * 0.003, 3),
            }
            for index in range(1, definition["d"] + 1)
        ]
    return {
        "description": "合成设备台账，字段 d 表示设备数量，capacity_n 表示单台设备单次批处理容量。",
        "equipment_types": definitions,
    }


def _build_project_catalog() -> dict[str, Any]:
    profiles = {
        "safety_check": {
            "lab_area": "safety_lab",
            "setup_minutes": 5,
            "operator_requirements": _operator_requirements(1, ["safety_engineer"], "shared_supervision", "running"),
            "consumable_type": "safety_probe",
            "consumable_units_per_batch": 1,
        },
        "emc_check": {
            "lab_area": "emc_lab",
            "setup_minutes": 10,
            "operator_requirements": _operator_requirements(3, ["emc_engineer", "assistant_operator"], "exclusive", "running"),
            "consumable_type": "emc_fixture",
            "consumable_units_per_batch": 1,
        },
        "performance_check": {
            "lab_area": "performance_lab",
            "setup_minutes": 5,
            "operator_requirements": _operator_requirements(1, ["performance_engineer"], "shared_supervision", "running"),
            "consumable_type": "load_fixture",
            "consumable_units_per_batch": 1,
        },
        "environmental_check": {
            "lab_area": "environmental_lab",
            "setup_minutes": 15,
            "operator_requirements": _operator_requirements(1, ["environmental_engineer"], "setup_only", "setup_unload"),
            "consumable_type": "environmental_tag",
            "consumable_units_per_batch": 1,
            "continuous_capable": True,
            "continuous_duration_profile": {"t_min": 1440, "t_mode": 2880, "t_max": 4320},
            "can_cross_workday": True,
        },
        "cb_review": {
            "lab_area": "review_lab",
            "setup_minutes": 0,
            "operator_requirements": _operator_requirements(1, ["certification_reviewer"], "exclusive", "running"),
            "consumable_type": "review_sheet",
            "consumable_units_per_batch": 1,
        },
    }
    flows = {
        "ccc": [
            ("ccc-safety", "safety_check", "safety_tester", 1, 35, 45, 70, "safety_engineer"),
            ("ccc-emc", "emc_check", "emc_tester", 2, 90, 120, 180, "emc_engineer"),
        ],
        "cvc": [
            ("cvc-performance", "performance_check", "performance_bench", 1, 45, 60, 100, "performance_engineer"),
            ("cvc-environment", "environmental_check", "environmental_chamber", 2, 120, 180, 4320, "environmental_engineer"),
        ],
        "international": [
            ("international-safety", "safety_check", "safety_tester", 1, 35, 50, 80, "safety_engineer"),
            ("international-emc", "emc_check", "emc_tester", 2, 100, 150, 220, "emc_engineer"),
            ("international-cb", "cb_review", "international_protocol_bench", 3, 50, 80, 130, "certification_reviewer"),
        ],
    }
    return {
        "description": "合成检测项目目录，t_min/t_mode/t_max 为仿真假设耗时分钟数。",
        "certification_flows": [
            {
                "certification_type": certification_type,
                "steps": [
                    {
                        "project_id": project_id,
                        "project_type": project_type,
                        "equipment_type": equipment_type,
                        "sequence": sequence,
                        "t_min": t_min,
                        "t_mode": t_mode,
                        "t_max": t_max,
                        "staff_role": staff_role,
                        **profiles[project_type],
                    }
                    for project_id, project_type, equipment_type, sequence, t_min, t_mode, t_max, staff_role in steps
                ],
            }
            for certification_type, steps in flows.items()
        ],
    }


def _operator_requirements(count: int, roles: list[str], mode: str, phase: str) -> dict[str, Any]:
    return {
        "required_operator_count": count,
        "required_roles": roles,
        "supervision_mode": mode,
        "staff_phase": phase,
    }


def _build_priority_rules() -> dict[str, Any]:
    return {
        "rule_set": "non_preemptive_priority_v1",
        "priority_order": ["vip", "urgent", "normal"],
        "preemption": False,
        "description": "非抢占式优先级规则：已开始检测任务不中断，VIP/加急只调整未开始任务的排序。",
        "sla_working_days": DEFAULT_CONFIG["sla_working_days"],
        "tie_breakers": ["arrival_time", "order_id"],
    }


def _build_operations_constraints() -> dict[str, Any]:
    return {
        "lab_areas": [
            {"lab_area": "intake", "display_name": "样品接收与前处理区"},
            {"lab_area": "safety_lab", "display_name": "安全实验室"},
            {"lab_area": "emc_lab", "display_name": "电磁兼容实验室"},
            {"lab_area": "performance_lab", "display_name": "性能实验室"},
            {"lab_area": "environmental_lab", "display_name": "环境实验室"},
            {"lab_area": "review_lab", "display_name": "国际认证评审区"},
        ],
        "calendar": {
            "timezone": "Asia/Shanghai",
            "working_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "closed_days": ["saturday", "sunday"],
        },
        "shifts": [
            {"shift_id": "intake_morning", "start": "09:00", "end": "12:00", "available_for": ["sample_intake", "preparation"]},
            {"shift_id": "lab_early", "start": "07:00", "end": "15:00", "available_for": ["safety_check", "performance_check"]},
            {"shift_id": "lab_day", "start": "09:00", "end": "18:00", "available_for": ["safety_check", "emc_check", "performance_check", "cb_review"]},
            {"shift_id": "lab_late", "start": "13:00", "end": "21:00", "available_for": ["emc_check", "sample_transfer"]},
            {"shift_id": "environment_continuous", "start": "08:00", "end": "20:00", "available_for": ["environmental_check"], "can_continue_during_lunch": True},
        ],
        "breaks": [
            {"name": "lunch", "start": "12:00", "end": "13:00", "staff_available": False}
        ],
        "staff_roles": [
            {"role": "safety_engineer", "staff_count": 4, "skills": ["safety_check"]},
            {"role": "emc_engineer", "staff_count": 4, "skills": ["emc_check"]},
            {"role": "assistant_operator", "staff_count": 4, "skills": ["emc_check", "performance_check", "environmental_check"]},
            {"role": "performance_engineer", "staff_count": 3, "skills": ["performance_check"]},
            {"role": "environmental_engineer", "staff_count": 2, "skills": ["environmental_check"]},
            {"role": "certification_reviewer", "staff_count": 2, "skills": ["cb_review"]},
            {"role": "sample_operator", "staff_count": 3, "skills": ["preprocessing"]},
            {"role": "transfer_operator", "staff_count": 3, "skills": ["sample_transfer"]},
        ],
        "employees": [
            {"employee_id": "emp-safety-1", "name": "安全工程师1", "roles": ["safety_engineer"], "skills": ["safety_check", "safety_tester"], "lab_areas": ["safety_lab"], "shift_id": "lab_day", "max_parallel_assignments": 2},
            {"employee_id": "emp-safety-2", "name": "安全工程师2", "roles": ["safety_engineer"], "skills": ["safety_check", "safety_tester"], "lab_areas": ["safety_lab"], "shift_id": "lab_day", "max_parallel_assignments": 2},
            {"employee_id": "emp-safety-3", "name": "安全工程师3", "roles": ["safety_engineer"], "skills": ["safety_check", "safety_tester"], "lab_areas": ["safety_lab"], "shift_id": "lab_day", "max_parallel_assignments": 2},
            {"employee_id": "emp-safety-4", "name": "安全工程师4", "roles": ["safety_engineer"], "skills": ["safety_check", "safety_tester"], "lab_areas": ["safety_lab"], "shift_id": "lab_day", "max_parallel_assignments": 2},
            {"employee_id": "emp-emc-1", "name": "EMC工程师1", "roles": ["emc_engineer"], "skills": ["emc_check", "emc_tester"], "lab_areas": ["emc_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            {"employee_id": "emp-emc-2", "name": "EMC工程师2", "roles": ["emc_engineer"], "skills": ["emc_check", "emc_tester"], "lab_areas": ["emc_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1, "unavailable_windows": [{"start": "2026-06-09T09:00:00+08:00", "end": "2026-06-09T12:00:00+08:00", "reason": "training"}]},
            {"employee_id": "emp-emc-3", "name": "EMC工程师3", "roles": ["emc_engineer"], "skills": ["emc_check", "emc_tester"], "lab_areas": ["emc_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            {"employee_id": "emp-assistant-1", "name": "助理操作员1", "roles": ["assistant_operator"], "skills": ["emc_check", "performance_check"], "lab_areas": ["emc_lab", "performance_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            {"employee_id": "emp-assistant-2", "name": "助理操作员2", "roles": ["assistant_operator"], "skills": ["emc_check", "environmental_check"], "lab_areas": ["emc_lab", "environmental_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            {"employee_id": "emp-assistant-3", "name": "助理操作员3", "roles": ["assistant_operator"], "skills": ["emc_check"], "lab_areas": ["emc_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            {"employee_id": "emp-performance-1", "name": "性能工程师1", "roles": ["performance_engineer"], "skills": ["performance_check", "performance_bench"], "lab_areas": ["performance_lab"], "shift_id": "lab_day", "max_parallel_assignments": 2},
            {"employee_id": "emp-performance-2", "name": "性能工程师2", "roles": ["performance_engineer"], "skills": ["performance_check", "performance_bench"], "lab_areas": ["performance_lab"], "shift_id": "lab_day", "max_parallel_assignments": 2},
            {"employee_id": "emp-environment-1", "name": "环境工程师1", "roles": ["environmental_engineer"], "skills": ["environmental_check", "environmental_chamber"], "lab_areas": ["environmental_lab"], "shift_id": "lab_day", "max_parallel_assignments": 3},
            {"employee_id": "emp-environment-2", "name": "环境工程师2", "roles": ["environmental_engineer"], "skills": ["environmental_check", "environmental_chamber"], "lab_areas": ["environmental_lab"], "shift_id": "lab_day", "max_parallel_assignments": 3},
            {"employee_id": "emp-review-1", "name": "认证评审员1", "roles": ["certification_reviewer"], "skills": ["cb_review"], "lab_areas": ["review_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            {"employee_id": "emp-review-2", "name": "认证评审员2", "roles": ["certification_reviewer"], "skills": ["cb_review"], "lab_areas": ["review_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            {"employee_id": "emp-prep-1", "name": "样品前处理员1", "roles": ["sample_operator"], "skills": ["preprocessing"], "lab_areas": ["intake"], "shift_id": "intake_morning", "max_parallel_assignments": 1},
            {"employee_id": "emp-prep-2", "name": "样品前处理员2", "roles": ["sample_operator"], "skills": ["preprocessing"], "lab_areas": ["intake"], "shift_id": "intake_morning", "max_parallel_assignments": 1},
            {"employee_id": "emp-prep-3", "name": "样品前处理员3", "roles": ["sample_operator"], "skills": ["preprocessing"], "lab_areas": ["intake"], "shift_id": "intake_morning", "max_parallel_assignments": 1},
            {"employee_id": "emp-transfer-1", "name": "转运员1", "roles": ["transfer_operator"], "skills": ["sample_transfer"], "lab_areas": ["intake", "safety_lab", "emc_lab", "performance_lab", "environmental_lab", "review_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            {"employee_id": "emp-transfer-2", "name": "转运员2", "roles": ["transfer_operator"], "skills": ["sample_transfer"], "lab_areas": ["intake", "safety_lab", "emc_lab", "performance_lab", "environmental_lab", "review_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            {"employee_id": "emp-transfer-3", "name": "转运员3", "roles": ["transfer_operator"], "skills": ["sample_transfer"], "lab_areas": ["intake", "safety_lab", "emc_lab", "performance_lab", "environmental_lab", "review_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
        ],
        "employee_unavailable_windows": [
            {"employee_id": "emp-environment-1", "start": "2026-06-16T13:00:00+08:00", "end": "2026-06-16T18:00:00+08:00", "reason": "calibration_support"},
        ],
        "preprocessing_resources": [
            {"resource_id": "prep-1", "resource_type": "prep_station"},
            {"resource_id": "prep-2", "resource_type": "prep_station"},
        ],
        "preprocessing_rules": {
            "default": {
                "required_minutes": 15,
                "lab_area": "intake",
                "required_roles": ["sample_operator"],
                "resource_type": "prep_station",
                "required_operator_count": 1,
            }
        },
        "transfer_resources": [
            {"resource_id": "cart-1", "resource_type": "transfer_cart"},
            {"resource_id": "cart-2", "resource_type": "transfer_cart"},
        ],
        "transfer_matrix": _build_transfer_matrix(),
        "consumables": {
            "safety_probe": {"daily_capacity": 80},
            "emc_fixture": {"daily_capacity": 45},
            "load_fixture": {"daily_capacity": 70},
            "environmental_tag": {"daily_capacity": 65},
            "review_sheet": {"daily_capacity": 60},
        },
        "maintenance_windows": [
            {"event_id": "maint-emc-001", "equipment_id": "emc_tester-1", "start": "2026-06-10T14:00:00+08:00", "end": "2026-06-10T17:00:00+08:00", "event_type": "planned_maintenance"},
            {"event_id": "maint-env-001", "equipment_id": "environmental_chamber-2", "start": "2026-06-17T09:00:00+08:00", "end": "2026-06-17T12:00:00+08:00", "event_type": "planned_maintenance"},
            {"event_id": "maint-safety-001", "equipment_id": "safety_tester-3", "start": "2026-06-24T15:00:00+08:00", "end": "2026-06-24T18:00:00+08:00", "event_type": "planned_maintenance"},
        ],
        "failure_events": [
            {"event_id": "fail-cb-001", "equipment_id": "international_protocol_bench-1", "start": "2026-06-19T10:00:00+08:00", "end": "2026-06-19T12:00:00+08:00", "event_type": "simulated_failure"}
        ],
    }


def _build_transfer_matrix() -> dict[str, dict[str, Any]]:
    lab_areas = ["safety_lab", "emc_lab", "performance_lab", "environmental_lab", "review_lab"]
    durations = {
        "intake->safety_lab": 8,
        "intake->emc_lab": 10,
        "intake->performance_lab": 10,
        "intake->environmental_lab": 12,
        "intake->review_lab": 8,
        "safety_lab->emc_lab": 10,
        "emc_lab->safety_lab": 10,
        "safety_lab->performance_lab": 12,
        "performance_lab->safety_lab": 12,
        "safety_lab->environmental_lab": 14,
        "environmental_lab->safety_lab": 14,
        "emc_lab->performance_lab": 12,
        "performance_lab->emc_lab": 12,
        "emc_lab->environmental_lab": 14,
        "environmental_lab->emc_lab": 14,
        "emc_lab->review_lab": 10,
        "review_lab->emc_lab": 10,
        "review_lab->safety_lab": 12,
        "performance_lab->environmental_lab": 12,
        "environmental_lab->performance_lab": 12,
    }
    matrix: dict[str, dict[str, Any]] = {}
    for source in ["intake", *lab_areas]:
        for target in lab_areas:
            if source == target:
                continue
            key = f"{source}->{target}"
            duration = durations.get(key, 15)
            matrix[key] = {
                "duration_minutes": duration,
                "required_roles": ["transfer_operator"],
                "resource_type": "transfer_cart",
                "required_operator_count": 1,
            }
    return matrix


def _build_order_arrivals(config: dict[str, Any], project_catalog: dict[str, Any]) -> dict[str, Any]:
    rng = random.Random(config["seed"])
    target_count = int(config["target_order_count"])
    arrival_times = _generate_arrival_times(config, rng)
    if len(arrival_times) < target_count:
        arrival_times.extend(_supplement_arrivals(config, rng, target_count - len(arrival_times)))
    if len(arrival_times) > target_count:
        arrival_times = sorted(rng.sample(arrival_times, target_count))
    else:
        arrival_times = sorted(arrival_times)

    order_types = _weighted_labels(config["order_type_distribution"], target_count, rng)
    certifications = _weighted_labels(config["certification_distribution"], target_count, rng)
    project_ids_by_cert = {
        flow["certification_type"]: [step["project_id"] for step in flow["steps"]]
        for flow in project_catalog["certification_flows"]
    }
    project_profiles = _project_profiles(project_catalog)
    route_templates = _build_route_templates()
    product_names = {
        "ccc": ["电热水壶", "电源适配器", "插座转换器", "照明灯具", "电线组件"],
        "cvc": ["空气净化器", "电饭煲", "吸尘器", "饮水机", "小型风扇"],
        "international": ["出口型电源模块", "国际版照明控制器", "CB认证家电样机", "出口型插接件"],
    }
    channels = ["企业委托", "平台预约", "批量送检", "认证项目转入"]

    orders: list[dict[str, Any]] = []
    for index, arrival in enumerate(arrival_times, start=1):
        order_type = order_types[index - 1]
        certification_type = certifications[index - 1]
        sample_quantity = _sample_quantity(rng)
        detection_route = _build_detection_route(
            certification_type=certification_type,
            route_templates=route_templates,
            project_profiles=project_profiles,
            rng=rng,
        )
        route_project_ids = [step["project_id"] for step in detection_route]
        requested_projects = _choose_requested_projects(rng, route_project_ids or project_ids_by_cert[certification_type])
        promised_finish = _add_working_days(arrival, int(config["sla_working_days"][order_type]))
        preprocessing_profile = _preprocessing_profile(sample_quantity, rng)
        orders.append(
            {
                "order_id": f"syn-order-{index:04d}",
                "arrival_time": arrival.isoformat(),
                "order_type": order_type,
                "sample_name": rng.choice(product_names[certification_type]),
                "product_category": _product_category(certification_type, rng),
                "sample_quantity": sample_quantity,
                "certification_type": certification_type,
                "requested_projects": requested_projects,
                "detection_route": detection_route,
                "preprocessing_profile": preprocessing_profile,
                "sample_storage_class": rng.choice(["ambient", "humidity_sensitive", "fragile"]),
                "transfer_requirements": {
                    "requires_chain_of_custody": order_type in {"vip", "urgent"},
                    "preferred_resource_type": "transfer_cart",
                },
                "promised_finish_time": promised_finish.isoformat(),
                "source_channel": rng.choice(channels),
                "synthetic": True,
            }
        )
    return {
        "description": "合成订单到达数据；detection_route 为订单级检测路线，duration_minutes 为基于 t_min/t_mode/t_max 抽样得到的实际仿真耗时。",
        "orders": orders,
    }


def _project_profiles(project_catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        step["project_id"]: step
        for flow in project_catalog["certification_flows"]
        for step in flow["steps"]
    }


def _build_route_templates() -> dict[str, list[list[str]]]:
    return {
        "ccc": [
            ["ccc-safety", "ccc-emc"],
            ["ccc-safety", "cvc-environment", "ccc-emc"],
            ["cvc-environment", "cvc-performance", "ccc-emc", "ccc-safety"],
        ],
        "cvc": [
            ["cvc-performance", "cvc-environment"],
            ["cvc-environment", "cvc-performance", "ccc-emc", "ccc-safety"],
            ["ccc-safety", "cvc-performance", "cvc-environment"],
        ],
        "international": [
            ["international-safety", "international-emc", "international-cb"],
            ["international-emc", "international-cb", "international-safety"],
            ["cvc-environment", "cvc-performance", "international-emc", "ccc-safety"],
        ],
    }


def _build_detection_route(
    certification_type: str,
    route_templates: dict[str, list[list[str]]],
    project_profiles: dict[str, dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    template = rng.choice(route_templates[certification_type])
    route = []
    for sequence, project_id in enumerate(template, start=1):
        profile = project_profiles[project_id]
        continuous_operation = False
        if profile["project_type"] == "environmental_check" and rng.random() < 0.22:
            continuous_profile = profile.get("continuous_duration_profile", {"t_min": 1440, "t_mode": 2880, "t_max": 4320})
            duration_minutes = int(
                round(
                    rng.triangular(
                        continuous_profile["t_min"],
                        continuous_profile["t_max"],
                        continuous_profile["t_mode"],
                    )
                )
            )
            continuous_operation = True
        elif profile["project_type"] == "environmental_check":
            duration_minutes = int(round(rng.triangular(120, 360, 180)))
        else:
            duration_minutes = int(round(rng.triangular(profile["t_min"], profile["t_max"], profile["t_mode"])))
        duration_minutes = max(profile["t_min"], min(profile["t_max"], duration_minutes))
        route.append(
            {
                "project_id": project_id,
                "project_type": profile["project_type"],
                "equipment_type": profile["equipment_type"],
                "lab_area": profile["lab_area"],
                "sequence": sequence,
                "duration_minutes": duration_minutes,
                "setup_minutes": profile["setup_minutes"],
                "duration_profile": {
                    "t_min": profile["t_min"],
                    "t_mode": profile["t_mode"],
                    "t_max": profile["t_max"],
                },
                "staff_role": profile["staff_role"],
                "operator_requirements": profile["operator_requirements"],
                "consumable_type": profile["consumable_type"],
                "consumable_units_per_batch": profile["consumable_units_per_batch"],
                "continuous_operation": continuous_operation,
                "can_cross_workday": bool(continuous_operation and profile.get("can_cross_workday")),
            }
        )
    return route


def _build_order_lifecycle_events(config: dict[str, Any], order_arrivals: dict[str, Any]) -> dict[str, Any]:
    rng = random.Random(int(config["seed"]) + 909)
    orders = order_arrivals["orders"]
    if not orders:
        return {"description": "合成订单生命周期事件。", "events": []}

    order_by_id = {order["order_id"]: order for order in orders}
    events: list[dict[str, Any]] = []

    def add_event(event_type: str, order: dict[str, Any], offset_hours: int, payload: dict[str, Any]) -> None:
        event_time = datetime.fromisoformat(order["arrival_time"]) + timedelta(hours=offset_hours)
        events.append(
            {
                "event_id": f"life-{len(events) + 1:04d}",
                "event_type": event_type,
                "order_id": order["order_id"],
                "event_time": event_time.isoformat(),
                "payload": payload,
                "synthetic": True,
            }
        )

    cancellation_count = max(1, len(orders) // 100)
    update_count = max(1, len(orders) // 125)
    retest_count = max(1, len(orders) // 160)
    candidates = orders[5:]

    for order in rng.sample(candidates, min(cancellation_count, len(candidates))):
        add_event("order_cancelled", order, 4, {"reason": "client_request", "applies_to": "not_started_steps"})

    for order in rng.sample(candidates, min(update_count, len(candidates))):
        add_event(
            "order_updated",
            order,
            6,
            {
                "field": "sample_quantity",
                "old_value": order["sample_quantity"],
                "new_value": order["sample_quantity"] + 1,
                "applies_to": "not_started_steps",
            },
        )

    retest_targets = rng.sample(candidates, min(retest_count, len(candidates)))
    available_retest_orders = [order for order in orders if not order.get("parent_order_id")][len(orders) - len(retest_targets):]
    for parent, retest in zip(retest_targets, available_retest_orders):
        failed_step = rng.choice(parent.get("detection_route") or [{"project_id": None, "project_type": "unknown"}])
        add_event(
            "detection_failed",
            parent,
            24,
            {
                "failed_project_id": failed_step.get("project_id"),
                "failed_project_type": failed_step.get("project_type"),
                "reason": "sample_result_out_of_tolerance",
            },
        )
        retest["parent_order_id"] = parent["order_id"]
        retest["retest_reason"] = "sample_result_out_of_tolerance"
        retest["source_failed_project_id"] = failed_step.get("project_id")
        retest["source_failed_project_type"] = failed_step.get("project_type")
        retest["arrival_time"] = (datetime.fromisoformat(parent["arrival_time"]) + timedelta(days=2, hours=2)).isoformat()
        retest["detection_route"] = [
            {**step, "sequence": index + 1}
            for index, step in enumerate(
                parent.get("detection_route", [])[
                    max(0, next((i for i, step in enumerate(parent.get("detection_route", [])) if step.get("project_id") == failed_step.get("project_id")), 0)) :
                ]
            )
        ] or retest["detection_route"]
        add_event(
            "retest_created",
            parent,
            50,
            {
                "retest_order_id": retest["order_id"],
                "failed_project_id": failed_step.get("project_id"),
                "reason": retest["retest_reason"],
            },
        )

    # Keep deterministic ordering after retest arrival adjustments.
    orders.sort(key=lambda item: (item["arrival_time"], item["order_id"]))
    assert set(order_by_id) == {order["order_id"] for order in orders}
    events.sort(key=lambda item: (item["event_time"], item["event_id"]))
    return {
        "description": "合成订单生命周期事件；用于验证取消、修改、检测失败和重测触发的重排机制。",
        "events": events,
    }


def _preprocessing_profile(sample_quantity: int, rng: random.Random) -> dict[str, Any]:
    return {
        "required_minutes": 10 + min(20, sample_quantity * 2) + rng.randint(0, 5),
        "lab_area": "intake",
        "required_roles": ["sample_operator"],
        "resource_type": "prep_station",
        "required_operator_count": 1,
    }


def _generate_arrival_times(config: dict[str, Any], rng: random.Random) -> list[datetime]:
    start_date = date.fromisoformat(config["period"]["start_date"])
    end_date = date.fromisoformat(config["period"]["end_date"])
    current = start_date
    arrivals: list[datetime] = []
    while current <= end_date:
        if current.weekday() < 5:
            for window in config["arrival_windows"]:
                start_time = _parse_time(window["start"])
                end_time = _parse_time(window["end"])
                duration_hours = _duration_hours(start_time, end_time)
                count = _poisson(float(window["lambda_per_hour"]) * duration_hours, rng)
                for _ in range(count):
                    offset_seconds = rng.randint(0, int(duration_hours * 3600) - 1)
                    arrivals.append(datetime.combine(current, start_time, tzinfo=TZ) + timedelta(seconds=offset_seconds))
        current += timedelta(days=1)
    return arrivals


def _supplement_arrivals(config: dict[str, Any], rng: random.Random, count: int) -> list[datetime]:
    start_date = date.fromisoformat(config["period"]["start_date"])
    end_date = date.fromisoformat(config["period"]["end_date"])
    weekdays = [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
        if (start_date + timedelta(days=offset)).weekday() < 5
    ]
    arrivals = []
    for _ in range(count):
        day = rng.choice(weekdays)
        window = rng.choice(config["arrival_windows"])
        start_time = _parse_time(window["start"])
        end_time = _parse_time(window["end"])
        duration_hours = _duration_hours(start_time, end_time)
        arrivals.append(datetime.combine(day, start_time, tzinfo=TZ) + timedelta(seconds=rng.randint(0, int(duration_hours * 3600) - 1)))
    return arrivals


def _weighted_labels(distribution: dict[str, float], count: int, rng: random.Random) -> list[str]:
    items = list(distribution.items())
    raw_counts = {key: int(count * weight) for key, weight in items}
    remainder = count - sum(raw_counts.values())
    ranked = sorted(items, key=lambda item: item[1], reverse=True)
    for index in range(remainder):
        raw_counts[ranked[index % len(ranked)][0]] += 1
    labels = [key for key, value in raw_counts.items() for _ in range(value)]
    rng.shuffle(labels)
    return labels


def _choose_requested_projects(rng: random.Random, project_ids: list[str]) -> list[str]:
    if rng.random() < 0.72:
        return []
    if len(project_ids) == 1 or rng.random() < 0.55:
        return [rng.choice(project_ids)]
    return sorted(rng.sample(project_ids, rng.randint(1, len(project_ids))))


def _sample_quantity(rng: random.Random) -> int:
    if rng.random() < 0.86:
        return rng.randint(1, 4)
    return rng.randint(5, 12)


def _product_category(certification_type: str, rng: random.Random) -> str:
    categories = {
        "ccc": ["家用电器", "电器附件", "照明电器", "电线电缆"],
        "cvc": ["家用电器", "电子产品", "质量评价样品"],
        "international": ["出口电器", "国际认证样品", "安全附件"],
    }
    return rng.choice(categories[certification_type])


def _add_working_days(arrival: datetime, days: int) -> datetime:
    current = arrival.date()
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return datetime.combine(current, time(18, 0), tzinfo=TZ)


def _poisson(lam: float, rng: random.Random) -> int:
    threshold = 2.718281828459045 ** (-lam)
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= rng.random()
    return count - 1


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _duration_hours(start: time, end: time) -> float:
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    return (end_minutes - start_minutes) / 60


def _write_knowledge_base(knowledge_dir: Path) -> None:
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    documents = {
        "certification_flows.md": "CCC、CVC、international 三类认证在本合成数据集中分别映射到安全/电磁兼容、性能/环境、国际安全/电磁兼容/CB资料评审流程。所有流程均包含 sequence 字段，用于验证检测步骤先后顺序。",
        "equipment_constraints.md": "设备约束包括设备类型 x、设备数量 d、批处理容量 n、检测耗时分布 t_min/t_mode/t_max，以及设备实例级维护窗口。订单级 detection_route 允许不同订单共享同一设备类型，从而形成资源竞争。",
        "priority_rules.md": "优先级规则采用非抢占式策略，排序为 vip、urgent、normal。已经开始的检测任务不中断，VIP和加急订单只影响尚未开始任务的队列顺序。",
        "operations_constraints.md": "运营约束包含工作日历、日班、午休不可用、员工实例、技能矩阵、样品前处理、跨实验室转运、耗材日配额、计划维护和模拟故障停机。排程验证会检查每个检测步骤至少绑定一名符合技能和实验室区域的操作人员。",
    }
    for filename, content in documents.items():
        (knowledge_dir / filename).write_text(content + "\n", encoding="utf-8")


def _write_readme(path: Path, config: dict[str, Any]) -> None:
    content = f"""# 合成拟真检测中心数据集

该目录为合成仿真数据集，用于多Agent检测队列系统的机制验证、压力测试和项目展示；其中设备数量、检测耗时、批处理容量、订单分布和优先级规则均为拟真假设，不代表某真实检测中心事实。

## 基本参数

- 随机种子：`{config["seed"]}`
- 仿真周期：`{config["period"]["start_date"]}` 至 `{config["period"]["end_date"]}`
- 目标订单量：`{config["target_order_count"]}`
- 订单类型分布：普通 75%，加急 18%，VIP 7%
- 认证类型分布：CCC 45%，CVC 35%，international 20%

## 文件说明

- `equipment_catalog.json`：设备类型、设备数量 d、设备实例、单台批处理容量 n。
- `project_catalog.json`：认证流程、检测步骤、设备需求、耗时分布 t、实验室区域、人员需求、准备时间和耗材需求。
- `order_arrivals.json`：合成订单到达记录；每个订单包含 `detection_route`、`preprocessing_profile` 和转运需求，用于表达订单级检测路线、共享设备类型和按 `t_min/t_mode/t_max` 抽样得到的步骤耗时。
- `order_lifecycle_events.json`：取消、修改、检测失败和重测创建事件，用于验证订单生命周期变化对重排的影响。
- `priority_rules.json`：非抢占式 VIP/加急优先规则。
- `operations_constraints.json`：班次、员工实例、前处理资源、转运资源、耗材日配额、维护和模拟故障。
- `knowledge_base/`：用于 RAG 检索的拟真知识文本。

## 生成与验证

```bash
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python scripts/generate_synthetic_center_dataset.py
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python scripts/validate_synthetic_center_dataset.py
```
"""
    path.write_text(content, encoding="utf-8")


def _build_manifest(output_dir: Path, config: dict[str, Any], order_arrivals: dict[str, Any]) -> dict[str, Any]:
    files = [
        "generation_config.json",
        "equipment_catalog.json",
        "project_catalog.json",
        "order_arrivals.json",
        "order_lifecycle_events.json",
        "priority_rules.json",
        "operations_constraints.json",
        "knowledge_base/certification_flows.md",
        "knowledge_base/equipment_constraints.md",
        "knowledge_base/priority_rules.md",
        "knowledge_base/operations_constraints.md",
        "README.md",
    ]
    return {
        "dataset_name": "scenario_synthetic_center",
        "dataset_version": config["dataset_version"],
        "synthetic": True,
        "seed": config["seed"],
        "period": config["period"],
        "order_count": len(order_arrivals["orders"]),
        "usage_boundary": "合成数据，仅用于机制验证、压力测试和项目展示，不代表真实机构参数。",
        "files": [{"path": item, "sha256": _sha256(output_dir / item)} for item in files],
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    report = generate_dataset(DATASET_DIR)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
