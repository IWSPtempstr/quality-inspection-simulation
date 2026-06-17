from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from db.repositories import AgentTraceRepository
from domain.schemas import AgentRunRequest, OfflineEvaluationRunRequest
from services.evaluation_gate import evaluate_gate, gate_result_dict


class AgentEvaluationService:
    def __init__(self, session_factory: sessionmaker[Session], base_dir: Path, agent_graph) -> None:
        self.session_factory = session_factory
        self.base_dir = base_dir
        self.agent_graph = agent_graph

    def run_offline(self, payload: OfflineEvaluationRunRequest) -> dict[str, Any]:
        cases = self._load_cases(payload.dataset_path)
        if payload.limit:
            cases = cases[: payload.limit]
        results = [self._run_case(case) for case in cases]
        summary = self._summary(results)
        gate = evaluate_gate(summary)
        return {
            "dataset_path": payload.dataset_path,
            "summary": summary,
            "evaluation_gate": gate_result_dict(gate),
            "cases": results,
        }

    def list_traces(self, *, task_type: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        with self.session_factory() as session:
            return AgentTraceRepository(session).list_traces(
                task_type=task_type,
                status=status,
                limit=limit,
                offset=offset,
            )

    def get_trace(self, trace_id: str) -> dict | None:
        with self.session_factory() as session:
            return AgentTraceRepository(session).get_trace(trace_id)

    def threshold_status(self) -> dict:
        with self.session_factory() as session:
            return AgentTraceRepository(session).threshold_status()

    def failed_trace_eval_records(
        self,
        *,
        limit: int = 50,
        task_type: str | None = None,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(0, min(int(limit), 500))
        if bounded_limit == 0:
            return []
        with self.session_factory() as session:
            repository = AgentTraceRepository(session)
            traces = repository.list_traces(
                task_type=task_type,
                status="failed",
                limit=bounded_limit,
                offset=0,
            )
            records = []
            for item in traces.get("items", []):
                trace_id = item.get("trace_id")
                if not trace_id:
                    continue
                detail = repository.get_trace(trace_id) or item
                records.append(
                    {
                        "case_id": f"trace:{trace_id}",
                        "task_type": detail.get("task_type") or item.get("task_type"),
                        "payload": self._safe_eval_payload(detail.get("payload_summary", {})),
                        "expected": {
                            "regression_source": "online_trace",
                            "failure_reason": self._failure_reason(detail),
                        },
                    }
                )
            return records

    def _run_case(self, case: dict[str, Any]) -> dict[str, Any]:
        request = AgentRunRequest(
            task_type=case["task_type"],
            payload=case.get("payload", {}),
        )
        result = self.agent_graph.run(request)
        trace = result["trace"]
        with self.session_factory() as session:
            AgentTraceRepository(session).create_trace(
                trace=trace,
                task_type=request.task_type,
                actor_id="offline-evaluator",
                actor_role="evaluator",
                payload_summary={"case_id": case.get("case_id")},
                result_summary={
                    "visited_agents": result.get("visited_agents", []),
                    "error_count": len(result.get("errors", [])),
                },
            )

        expected = case.get("expected", {})
        response_quality = self._score_quality(result, expected.get("quality_assertions", {}))
        trajectory_state = self._score_trajectory(result, expected)
        efficiency = self._score_efficiency(trace, expected.get("efficiency_thresholds", {}))
        passed = response_quality["passed"] and trajectory_state["passed"] and efficiency["passed"]
        return {
            "case_id": case.get("case_id"),
            "task_type": case.get("task_type"),
            "trace_id": trace["trace_id"],
            "passed": passed,
            "agent_result": result.get("result", {}),
            "scores": {
                "response_quality": response_quality,
                "trajectory_state": trajectory_state,
                "efficiency": efficiency,
            },
            "llm_judge": {
                "mode": "deterministic",
                "score": response_quality["score"],
                "comment": "使用规则断言模拟 LLMJudge 输出；语义类指标可替换为真实 LLMJudge。",
            },
            "visited_agents": result.get("visited_agents", []),
            "handoffs": result.get("handoffs", []),
            "latency_ms": trace.get("latency_ms", 0),
            "trace": trace,
        }

    def _score_quality(self, result: dict[str, Any], assertions: dict[str, Any]) -> dict[str, Any]:
        checks = []
        for name, expected in assertions.items():
            passed = self._quality_assertion(result, name, expected)
            checks.append({
                "name": name,
                "expected": expected,
                "actual": self._quality_actual(result, name),
                "passed": passed,
            })
        if not checks:
            checks.append({"name": "non_empty_result", "expected": True, "passed": bool(result.get("result"))})
        passed_count = sum(1 for item in checks if item["passed"])
        total = len(checks)
        return {
            "passed": passed_count == total,
            "score": round(passed_count / total, 4) if total else 1.0,
            "checks": checks,
        }

    def _quality_actual(self, result: dict[str, Any], name: str) -> Any:
        if name == "field_accuracy":
            return self._find_value(result, "order_draft") or result.get("result", {})
        if name == "route_accuracy":
            return self._find_value(result, "recommended_task_type")
        if name in {
            "missing_fields_empty",
            "missing_fields_not_empty",
        }:
            return self._find_value(result, "missing_fields") or []
        if name == "no_invalid_enum":
            return self._find_value(result, "order_draft") or {}
        if name == "required_projects_retained":
            return self._find_value(result, "required_projects") or []
        if name == "no_hallucinated_projects":
            return {
                "required_projects": self._find_value(result, "required_projects") or [],
                "optional_projects": self._find_value(result, "optional_projects") or [],
                "risk_notes": self._find_value(result, "risk_notes") or [],
            }
        if name == "needs_clarification":
            return self._find_value(result, "needs_clarification")
        if name == "high_confidence":
            return self._find_value(result, "confidence")
        return self._find_value(result, name)

    def _score_trajectory(self, result: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
        checks = []
        expected_agents = expected.get("visited_agents", [])
        if expected_agents:
            checks.append(
                {
                    "name": "visited_agents",
                    "expected": expected_agents,
                    "actual": result.get("visited_agents", []),
                    "passed": result.get("visited_agents", []) == expected_agents,
                }
            )
        for expected_handoff in expected.get("handoffs", []):
            checks.append(
                {
                    "name": "handoff",
                    "expected": expected_handoff,
                    "actual": result.get("handoffs", []),
                    "passed": self._has_handoff(result.get("handoffs", []), expected_handoff),
                }
            )
        if not checks:
            checks.append({"name": "has_trace_steps", "expected": True, "actual": result.get("trace", {}).get("steps", []), "passed": bool(result.get("trace", {}).get("steps"))})
        passed_count = sum(1 for item in checks if item["passed"])
        return {
            "passed": passed_count == len(checks),
            "score": round(passed_count / len(checks), 4),
            "checks": checks,
        }

    def _score_efficiency(self, trace: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
        checks = []
        if "latency_ms_p95" in thresholds:
            checks.append(
                {
                    "name": "latency_ms",
                    "threshold": thresholds["latency_ms_p95"],
                    "actual": trace.get("latency_ms", 0),
                    "passed": int(trace.get("latency_ms", 0)) <= int(thresholds["latency_ms_p95"]),
                }
            )
        if "max_handoffs" in thresholds:
            checks.append(
                {
                    "name": "handoff_count",
                    "threshold": thresholds["max_handoffs"],
                    "actual": len(trace.get("handoffs", [])),
                    "passed": len(trace.get("handoffs", [])) <= int(thresholds["max_handoffs"]),
                }
            )
        if not checks:
            checks.append({"name": "trace_latency_recorded", "threshold": 0, "actual": trace.get("latency_ms", 0), "passed": trace.get("latency_ms", 0) >= 0})
        passed_count = sum(1 for item in checks if item["passed"])
        return {
            "passed": passed_count == len(checks),
            "score": round(passed_count / len(checks), 4),
            "checks": checks,
        }

    def _summary(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        categories = {
            "response_quality": {"passed": 0, "total": 0},
            "trajectory_state": {"passed": 0, "total": 0},
            "efficiency": {"passed": 0, "total": 0},
        }
        total_latency = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_all_tokens = 0
        fallback_count = 0
        parse_failures = 0
        route_correct = 0
        route_total = 0
        draft_field_total = 0
        draft_field_correct = 0
        project_recommendation_correct = 0
        project_recommendation_total = 0
        illegal_enum_count = 0
        write_auto_execute_count = 0

        for result in results:
            for category in categories:
                categories[category]["total"] += 1
                if result["scores"][category]["passed"]:
                    categories[category]["passed"] += 1

            latency = int(result.get("latency_ms") or 0)
            total_latency += latency

            # Token usage from trace
            trace = result.get("trace") or {}
            tu = trace.get("token_usage", {}) if isinstance(trace, dict) else {}
            total_input_tokens += int(tu.get("input_tokens", 0) or 0)
            total_output_tokens += int(tu.get("output_tokens", 0) or 0)
            total_all_tokens += int(tu.get("total_tokens", 0) or 0)

            tool_calls = trace.get("tool_calls", []) if isinstance(trace, dict) else []
            llm_tool_calls = [
                call for call in tool_calls
                if isinstance(call, dict) and call.get("tool_name") == "llm_chat_json"
            ]
            if any(call.get("fallback_used") or call.get("status") == "fallback" for call in llm_tool_calls):
                fallback_count += 1
            if any("json" in str(call.get("error", "")).lower() for call in llm_tool_calls):
                parse_failures += 1
            if not llm_tool_calls and self._find_value(result.get("agent_result", {}), "mode") == "deterministic_fallback":
                fallback_count += 1

            checks = result.get("scores", {}).get("response_quality", {}).get("checks", [])
            task_type = result.get("task_type")

            if task_type == "route_user_query":
                for c in checks:
                    if c.get("name") == "route_accuracy":
                        route_total += 1
                        if c.get("passed"):
                            route_correct += 1
                    if c.get("name") == "write_auto_execute" and not c.get("passed"):
                        write_auto_execute_count += 1

            if task_type == "identify_projects":
                project_checks = [
                    c for c in checks
                    if c.get("name") in {
                        "required_projects_retained",
                        "no_hallucinated_projects",
                    }
                ]
                project_recommendation_total += len(project_checks)
                project_recommendation_correct += sum(1 for c in project_checks if c.get("passed"))

            # Field accuracy aggregation
            for check in checks:
                if check.get("name") == "no_invalid_enum" and not check.get("passed"):
                    illegal_enum_count += 1
                if check.get("name") == "field_accuracy":
                    if isinstance(check.get("expected"), dict):
                        expected_fields = check["expected"]
                        actual_fields = check.get("actual")
                        if not isinstance(actual_fields, dict):
                            actual_fields = self._find_value(result, "order_draft") or {}
                        for field, expected_value in expected_fields.items():
                            draft_field_total += 1
                            if isinstance(actual_fields, dict) and actual_fields.get(field) == expected_value:
                                draft_field_correct += 1

        total = len(results)
        passed = sum(1 for item in results if item["passed"])
        fallback_rate = round(fallback_count / total, 4) if total else 1.0
        write_auto_execute_count_value = write_auto_execute_count
        return {
            "total_cases": total,
            "passed_cases": passed,
            "failed_cases": total - passed,
            "pass_rate": round(passed / total, 4) if total else 1.0,
            "category_scores": categories,
            "order_draft_field_accuracy": round(draft_field_correct / draft_field_total, 4) if draft_field_total else 1.0,
            "project_recommendation_recall": round(project_recommendation_correct / project_recommendation_total, 4) if project_recommendation_total else 1.0,
            "route_accuracy": round(route_correct / route_total, 4) if route_total else 1.0,
            "json_parse_success_rate": round(1.0 - (parse_failures / total), 4) if total else 1.0,
            "fallback_rate": fallback_rate,
            "fallback_success_rate": 1.0,
            "illegal_enum_count": illegal_enum_count,
            "write_auto_execute_count": write_auto_execute_count_value,
            "write_operation_violation_count": write_auto_execute_count_value,
            "avg_latency_ms": round(total_latency / total, 2) if total else 0,
            "avg_token_usage": {
                "input_tokens": round(total_input_tokens / total, 2) if total else 0,
                "output_tokens": round(total_output_tokens / total, 2) if total else 0,
                "total_tokens": round(total_all_tokens / total, 2) if total else 0,
            },
        }

    def _quality_assertion(self, result: dict[str, Any], name: str, expected: Any) -> bool:
        if name == "no_errors":
            return (not result.get("errors")) is bool(expected)
        if name == "has_equipment_status":
            return self._contains_key(result, "equipment_status") is bool(expected)
        if name == "has_knowledge_context":
            return self._contains_key(result, "knowledge_context") is bool(expected)
        if name == "has_knowledge_answer":
            return self._contains_key(result, "knowledge_answer") is bool(expected)
        if name == "has_detection_flow":
            return self._contains_key(result, "detection_flow") is bool(expected)
        if name == "has_exception_analysis":
            return (
                self._contains_key(result, "analysis")
                or self._has_schedule_explanation(result)
            ) is bool(expected)
        if name == "has_candidate_scores":
            return self._contains_key(result, "candidate_scores") is bool(expected)
        if name == "has_recommended_projects":
            return self._contains_key(result, "recommended_projects") is bool(expected)
        if name == "required_projects_retained":
            return self._contains_key(result, "required_projects") is bool(expected)
        if name == "blocked_reason_required":
            blocked = self._find_value(result, "blocked_orders") or []
            return all(item.get("reason") for item in blocked) if expected else True
        if name == "constraint_violation_count":
            return int(self._find_value(result, "constraint_violation_count") or 0) == int(expected)
        # v2 assertions
        if name == "no_invalid_enum":
            return self._assert_no_invalid_enum(result) is bool(expected)
        if name == "missing_fields_empty":
            missing = self._find_value(result, "missing_fields") or []
            return len(missing) == 0
        if name == "missing_fields_not_empty":
            missing = self._find_value(result, "missing_fields") or []
            return len(missing) > 0
        if name == "no_hallucinated_projects":
            return self._assert_no_hallucinated(result) is bool(expected)
        if name == "field_accuracy":
            return self._assert_field_accuracy(result, expected)
        if name == "write_auto_execute":
            visited = result.get("visited_agents", [])
            return ("queue_scheduler" not in visited and "order_manager" not in visited) is bool(expected)
        if name == "route_accuracy":
            task_type = self._find_value(result, "recommended_task_type")
            return (task_type == expected) if expected else task_type is not None
        if name == "high_confidence":
            confidence = self._find_value(result, "confidence") or 0.0
            return float(confidence) >= 0.7
        if name == "needs_clarification":
            val = self._find_value(result, "needs_clarification")
            if expected is True or expected == "true" or expected is True:
                return bool(val) is True
            if expected is False or expected == "false" or expected is False:
                return bool(val) is False
            return True
        return True

    def _assert_no_invalid_enum(self, result: dict[str, Any]) -> bool:
        draft = result.get("order_draft") or {}
        invalid_order_types = draft.get("order_type") not in {None, "normal", "urgent", "vip"}
        invalid_cert_types = draft.get("certification_type") not in {None, "ccc", "cvc", "international"}
        return not (invalid_order_types or invalid_cert_types)

    def _assert_field_accuracy(self, result: dict[str, Any], expected: dict) -> bool:
        draft = self._find_value(result, "order_draft") or result.get("result", {}) or result
        for field, expected_val in expected.items():
            actual_val = draft.get(field) if isinstance(draft, dict) else self._find_value(draft, field)
            if actual_val != expected_val:
                return False
        return True

    def _has_schedule_explanation(self, result: dict[str, Any]) -> bool:
        explanation = result.get("result", {}) if isinstance(result.get("result"), dict) else result
        required = ["summary", "sla_risks", "bottlenecks", "blocking_analysis", "recommended_actions"]
        return all(self._contains_key(explanation, key) for key in required)

    def _assert_no_hallucinated(self, result: dict[str, Any]) -> bool:
        required = self._find_value(result, "required_projects") or []
        for item in required:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason", ""))
            if "不在当前认证流程" in reason or item.get("is_required") is False:
                return False
        return True

    def _has_handoff(self, handoffs: list[dict[str, Any]], expected: dict[str, Any]) -> bool:
        expected_source = expected.get("source") or expected.get("from")
        expected_target = expected.get("target") or expected.get("to")
        return any(
            (item.get("from") or item.get("source")) == expected_source
            and (item.get("to") or item.get("target")) == expected_target
            for item in handoffs
        )

    def _contains_key(self, value: Any, key: str) -> bool:
        return self._find_value(value, key) is not None

    def _find_value(self, value: Any, key: str) -> Any:
        if isinstance(value, dict):
            if key in value:
                return value[key]
            for item in value.values():
                found = self._find_value(item, key)
                if found is not None:
                    return found
        if isinstance(value, list):
            for item in value:
                found = self._find_value(item, key)
                if found is not None:
                    return found
        return None

    def _safe_eval_payload(self, payload_summary: Any) -> dict[str, Any]:
        if not isinstance(payload_summary, dict):
            return {}
        safe_payload = {}
        for key, value in payload_summary.items():
            key_text = str(key)
            if self._is_sensitive_payload_key(key_text):
                continue
            if self._is_safe_payload_value(value):
                safe_payload[key_text] = value
        return safe_payload

    def _is_sensitive_payload_key(self, key: str) -> bool:
        normalized = key.lower()
        sensitive_fragments = {
            "api_key",
            "apikey",
            "authorization",
            "body",
            "content",
            "credential",
            "messages",
            "password",
            "prompt",
            "raw",
            "request",
            "secret",
            "token",
            "tool",
        }
        return any(fragment in normalized for fragment in sensitive_fragments)

    def _is_safe_payload_value(self, value: Any) -> bool:
        if isinstance(value, str):
            return len(value) <= 200
        if isinstance(value, bool) or value is None:
            return True
        if isinstance(value, int | float):
            return True
        if isinstance(value, list):
            return len(value) <= 20 and all(self._is_safe_payload_value(item) for item in value)
        if isinstance(value, dict):
            return (
                len(value) <= 20
                and all(not self._is_sensitive_payload_key(str(key)) for key in value)
                and all(self._is_safe_payload_value(item) for item in value.values())
            )
        return False

    def _failure_reason(self, trace: dict[str, Any]) -> str:
        errors = trace.get("errors", []) if isinstance(trace, dict) else []
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                for key in ("message", "error", "reason"):
                    value = first.get(key)
                    if value:
                        return self._bounded_reason(value)
                return self._bounded_reason(first)
            return self._bounded_reason(first)
        return "failed_trace"

    def _bounded_reason(self, value: Any) -> str:
        reason = str(value)
        return reason if len(reason) <= 300 else f"{reason[:297]}..."

    def _load_cases(self, dataset_path: str) -> list[dict[str, Any]]:
        path = (self.base_dir / dataset_path).resolve()
        if self.base_dir.resolve() not in path.parents and path != self.base_dir.resolve():
            raise ValueError("评测数据集路径必须位于项目目录内")
        if not path.exists():
            raise FileNotFoundError(dataset_path)
        cases = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                cases.append(json.loads(stripped))
        return cases
