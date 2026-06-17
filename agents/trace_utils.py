from __future__ import annotations

from typing import Any, Iterable, Mapping


def json_ready(value: Any) -> Any:
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def agent_tool_calls(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    agent_name = state.get("agent_name")
    result = state.get("result", {})
    llm_meta = result.get("llm_metadata") if isinstance(result, dict) else None
    if isinstance(llm_meta, dict) and llm_meta.get("llm_called"):
        calls.append({
            "tool_name": "llm_chat_json",
            "status": "fallback" if llm_meta.get("fallback_used") else "success",
            "model": llm_meta.get("model", "unknown"),
            "fallback_used": llm_meta.get("fallback_used", False),
            "error": llm_meta.get("error"),
        })
    if agent_name == "equipment_monitor":
        calls.append({"tool_name": "get_equipment_status", "status": "success", "adapter": "mcp_or_local"})
    if agent_name == "rag_retriever":
        context = result.get("knowledge_context", [])
        calls.append({"tool_name": "knowledge_search", "status": "success", "result_count": len(context)})
    if agent_name == "queue_scheduler":
        calls.append({"tool_name": state.get("task_type", "queue_task"), "status": "success"})
    if agent_name == "notification_agent":
        calls.append({"tool_name": state.get("task_type", "notification_task"), "status": "success"})
    return calls


def agent_token_usage(state: Mapping[str, Any]) -> dict[str, int]:
    result = state.get("result", {})
    llm_meta = result.get("llm_metadata") if isinstance(result, dict) else None
    if isinstance(llm_meta, dict) and llm_meta.get("token_usage"):
        return _token_usage_dict(llm_meta["token_usage"])
    analysis = result.get("analysis", {}) if isinstance(result, dict) else {}
    token_usage = analysis.get("token_usage") if isinstance(analysis, dict) else None
    if isinstance(token_usage, dict):
        return _token_usage_dict(token_usage)
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def aggregate_token_usage(items: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for item in items:
        usage = item.get("token_usage", {})
        for key in totals:
            totals[key] += int(usage.get(key, 0) or 0)
    return totals


def _token_usage_dict(value: Mapping[str, Any]) -> dict[str, int]:
    return {
        "input_tokens": int(value.get("input_tokens", 0)),
        "output_tokens": int(value.get("output_tokens", 0)),
        "total_tokens": int(value.get("total_tokens", 0)),
    }
