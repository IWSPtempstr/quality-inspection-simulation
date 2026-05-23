from __future__ import annotations

from collections import OrderedDict


def format_schedule_summary(run: dict) -> dict:
    return {
        "id": run["id"],
        "scheduled_count": run["scheduled_count"],
        "blocked_count": run["blocked_count"],
        "created_at": _serialize(run.get("created_at")),
    }


def format_schedule_detail(schedule: dict) -> dict:
    orders: "OrderedDict[str, dict]" = OrderedDict()
    blocked_orders: list[dict] = []

    for step in schedule.get("steps", []):
        status = step.get("status")
        if status == "blocked":
            reason = step.get("blocked_reason")
            blocked_orders.append(
                {
                    "id": step["order_id"],
                    "order_type": step["order_type"],
                    "sample_name": step["sample_name"],
                    "certification_type": step["certification_type"],
                    "status": status,
                    "reason": reason,
                    "reason_detail": explain_blocked_reason(reason),
                }
            )
            continue

        sla_risk_level = _sla_risk_level(step.get("sla_status"), step.get("delay_minutes"))
        order = orders.setdefault(
            step["order_id"],
            {
                "id": step["order_id"],
                "order_type": step["order_type"],
                "sample_name": step["sample_name"],
                "certification_type": step["certification_type"],
                "status": status,
                "arrival_time": _serialize(step.get("arrival_time")),
                "promised_finish_time": _serialize(step.get("promised_finish_time")),
                "sla_status": step.get("sla_status"),
                "delay_minutes": step.get("delay_minutes"),
                "sla_risk_level": sla_risk_level,
                "steps": [],
            },
        )
        if step.get("project_id") or step.get("step_kind"):
            order["steps"].append(
                {
                    "id": step.get("id"),
                    "run_id": step.get("run_id"),
                    "position": step.get("position"),
                    "step_kind": step.get("step_kind"),
                    "project_id": step.get("project_id"),
                    "project_type": step.get("project_type"),
                    "equipment_type": step.get("equipment_type"),
                    "equipment_id": step.get("equipment_id"),
                    "lab_area": step.get("lab_area"),
                    "assigned_employee_ids": step.get("assigned_employee_ids", []),
                    "resource_ids": step.get("resource_ids", []),
                    "constraint_detail": step.get("constraint_detail", {}),
                    "setup_minutes": step.get("setup_minutes"),
                    "staff_role": step.get("staff_role"),
                    "consumable_type": step.get("consumable_type"),
                    "consumable_units": step.get("consumable_units"),
                    "sequence": step.get("sequence"),
                    "start_minute": step.get("start_minute"),
                    "start_time": _serialize(step.get("start_time")),
                    "duration_minutes": step.get("duration_minutes"),
                    "end_minute": step.get("end_minute"),
                    "end_time": _serialize(step.get("end_time")),
                    "batch_count": step.get("batch_count"),
                    "required_batches": step.get("required_batches"),
                    "sla_status": step.get("sla_status"),
                    "delay_minutes": step.get("delay_minutes"),
                    "sla_risk_level": sla_risk_level,
                    "execution_status": step.get("execution_status"),
                    "locked": bool(step.get("locked")),
                    "actual_start_time": _serialize(step.get("actual_start_time")),
                    "actual_end_time": _serialize(step.get("actual_end_time")),
                    "execution_note": step.get("execution_note"),
                }
            )

    return {
        "id": schedule["id"],
        "scheduled_count": schedule["scheduled_count"],
        "blocked_count": schedule["blocked_count"],
        "created_at": _serialize(schedule.get("created_at")),
        "metrics": schedule.get("metrics", {}),
        "scheduled_orders": list(orders.values()),
        "blocked_orders": blocked_orders,
        "steps": schedule.get("steps", []),
        "gantt": format_gantt(schedule),
    }


def format_gantt(schedule: dict) -> dict:
    bars = []
    for step in schedule.get("steps", []):
        if not step.get("step_kind") or not step.get("start_time") or not step.get("end_time"):
            continue
        resource_id = step.get("equipment_id") or (step.get("resource_ids") or [None])[0]
        bars.append(
            {
                "id": step["id"],
                "run_id": step["run_id"],
                "order_id": step["order_id"],
                "sample_name": step["sample_name"],
                "step_kind": step.get("step_kind"),
                "project_type": step.get("project_type"),
                "resource_id": resource_id,
                "equipment_type": step.get("equipment_type"),
                "lab_area": step.get("lab_area"),
                "start_time": _serialize(step.get("start_time")),
                "end_time": _serialize(step.get("end_time")),
                "duration_minutes": step.get("duration_minutes"),
                "sla_status": step.get("sla_status"),
                "delay_minutes": step.get("delay_minutes"),
                "sla_risk_level": _sla_risk_level(step.get("sla_status"), step.get("delay_minutes")),
                "execution_status": step.get("execution_status") or step.get("status"),
                "locked": bool(step.get("locked")),
                "assigned_employee_ids": step.get("assigned_employee_ids", []),
            }
        )
    rows = {}
    for bar in bars:
        key = bar["resource_id"] or bar["lab_area"] or "unassigned"
        rows.setdefault(key, []).append(bar)
    return {
        "run_id": schedule["id"],
        "created_at": _serialize(schedule.get("created_at")),
        "rows": [{"resource_id": key, "bars": value} for key, value in sorted(rows.items())],
        "bars": bars,
    }


def _serialize(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _sla_risk_level(sla_status: str | None, delay_minutes: int | None) -> str:
    if sla_status == "delayed" or int(delay_minutes or 0) > 0:
        return "delayed"
    if sla_status == "on_time":
        return "on_time"
    return "not_applicable"


def explain_blocked_reason(reason: str | None) -> dict:
    text = reason or "unknown"
    lower = text.lower()
    if "no detection flow" in lower:
        return {
            "category": "route_missing",
            "summary": "未找到可用检测流程。",
            "suggested_action": "检查认证类型、requested_projects 或订单级 detection_route。",
            "raw_reason": text,
        }
    if "preprocessing" in lower:
        return {
            "category": "preprocessing_unavailable",
            "summary": "样品前处理资源或人员不可用。",
            "suggested_action": "检查前处理工位、人员技能和班次约束。",
            "raw_reason": text,
        }
    if "transfer" in lower:
        return {
            "category": "transfer_unavailable",
            "summary": f"跨实验室转运资源不可用：{text}",
            "suggested_action": "检查转运资源、实验室区域路径和转运人员配置。",
            "raw_reason": text,
        }
    if "equipment" in lower or "personnel" in lower or "consumable" in lower:
        return {
            "category": "resource_unavailable",
            "summary": f"设备、人员或耗材资源不可用：{text}",
            "suggested_action": "检查设备状态、操作人员技能/并行上限和耗材日配额。",
            "raw_reason": text,
        }
    return {
        "category": "unknown",
        "summary": text,
        "suggested_action": "查看订单路线、资源约束和排程事件日志。",
        "raw_reason": text,
    }
