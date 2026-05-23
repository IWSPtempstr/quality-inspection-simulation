from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from db.repositories import AgentTraceRepository
from domain.schemas import AgentRunRequest, OfflineEvaluationRunRequest


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
        return {
            "dataset_path": payload.dataset_path,
            "summary": self._summary(results),
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
        }

    def _score_quality(self, result: dict[str, Any], assertions: dict[str, Any]) -> dict[str, Any]:
        checks = []
        for name, expected in assertions.items():
            passed = self._quality_assertion(result, name, expected)
            checks.append({"name": name, "expected": expected, "passed": passed})
        if not checks:
            checks.append({"name": "non_empty_result", "expected": True, "passed": bool(result.get("result"))})
        passed_count = sum(1 for item in checks if item["passed"])
        total = len(checks)
        return {
            "passed": passed_count == total,
            "score": round(passed_count / total, 4) if total else 1.0,
            "checks": checks,
        }

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
        for result in results:
            for category in categories:
                categories[category]["total"] += 1
                if result["scores"][category]["passed"]:
                    categories[category]["passed"] += 1
        total = len(results)
        passed = sum(1 for item in results if item["passed"])
        return {
            "total_cases": total,
            "passed_cases": passed,
            "failed_cases": total - passed,
            "pass_rate": round(passed / total, 4) if total else 1.0,
            "category_scores": categories,
        }

    def _quality_assertion(self, result: dict[str, Any], name: str, expected: Any) -> bool:
        if name == "no_errors":
            return (not result.get("errors")) is bool(expected)
        if name == "has_equipment_status":
            return self._contains_key(result, "equipment_status") is bool(expected)
        if name == "has_knowledge_context":
            return self._contains_key(result, "knowledge_context") is bool(expected)
        if name == "has_detection_flow":
            return self._contains_key(result, "detection_flow") is bool(expected)
        if name == "has_exception_analysis":
            return self._contains_key(result, "analysis") is bool(expected)
        if name == "has_candidate_scores":
            return self._contains_key(result, "candidate_scores") is bool(expected)
        if name == "blocked_reason_required":
            blocked = self._find_value(result, "blocked_orders") or []
            return all(item.get("reason") for item in blocked) if expected else True
        if name == "constraint_violation_count":
            return int(self._find_value(result, "constraint_violation_count") or 0) == int(expected)
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
