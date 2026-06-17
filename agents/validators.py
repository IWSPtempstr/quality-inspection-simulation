from __future__ import annotations

from typing import Any, Iterable, Mapping


DEFAULT_ALLOWED_ROUTE_PAIRS = frozenset({
    ("draft_order_from_text", "order_manager"),
    ("list_orders", "order_manager"),
    ("identify_projects", "project_identifier"),
    ("search_knowledge", "rag_retriever"),
    ("query_queue", "queue_scheduler"),
    ("explain_schedule", "queue_scheduler"),
    ("rebuild_queue", "queue_scheduler"),
    ("query_notifications", "notification_agent"),
    ("analyze_exception", "exception_analyzer"),
})


def validate_route_recommendation(value: Mapping[str, Any]) -> bool:
    return validate_route_recommendation_for_pairs(
        value,
        DEFAULT_ALLOWED_ROUTE_PAIRS,
    )


def validate_route_recommendation_for_pairs(
    value: Mapping[str, Any],
    allowed_pairs: Iterable[tuple[str, str]],
) -> bool:
    if not isinstance(value, Mapping):
        return False
    task_type = value.get("recommended_task_type")
    target_agent = value.get("target_agent")
    return (task_type, target_agent) in set(allowed_pairs)


def valid_knowledge_answer(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping):
        return False
    if not isinstance(value.get("answer"), str) or not value["answer"].strip():
        return False
    if not isinstance(value.get("citations"), list):
        return False
    try:
        float(value.get("confidence", 0.0))
    except (TypeError, ValueError):
        return False
    return True


def valid_schedule_explanation(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping):
        return False
    required_types = {
        "summary": str,
        "sla_risks": list,
        "bottlenecks": list,
        "blocking_analysis": list,
        "recommended_actions": list,
    }
    return all(
        isinstance(value.get(key), expected_type)
        for key, expected_type in required_types.items()
    )


def valid_exception_analysis(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping):
        return False
    required_types = {
        "root_causes": list,
        "affected_orders": list,
        "bottleneck_resources": list,
        "risk_level": str,
        "recommended_actions": list,
    }
    if not all(
        isinstance(value.get(key), expected_type)
        for key, expected_type in required_types.items()
    ):
        return False
    return value.get("risk_level") in {"critical", "high", "medium", "low"}
