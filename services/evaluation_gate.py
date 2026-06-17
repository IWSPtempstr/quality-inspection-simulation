from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

POLICY_VERSION = "harness-eval-gate-v2"
DEFAULT_GATE_CHECKS = {
    "fallback_success_rate": {"threshold": 1.0, "operator": "eq"},
    "write_operation_violation_count": {"threshold": 0, "operator": "eq"},
    "json_parse_success_rate": {"threshold": 0.95, "operator": "gte"},
    "route_accuracy": {"threshold": 0.9, "operator": "gte"},
    "order_draft_field_accuracy": {"threshold": 0.9, "operator": "gte"},
    "project_recommendation_recall": {"threshold": 0.9, "operator": "gte"},
    "pass_rate": {"threshold": 0.8, "operator": "gte"},
}


@dataclass(frozen=True)
class EvaluationGateResult:
    passed: bool
    failures: list[str]
    metrics: dict[str, Any]
    policy_version: str = POLICY_VERSION


def evaluate_gate(summary: Mapping[str, Any]) -> EvaluationGateResult:
    failures: list[str] = []
    metrics: dict[str, Any] = {}

    for name, policy in DEFAULT_GATE_CHECKS.items():
        if name not in summary:
            continue

        threshold = policy["threshold"]
        operator = policy["operator"]
        actual = summary[name]
        passed = _passes(actual, threshold, operator)
        metrics[name] = {
            "actual": actual,
            "threshold": threshold,
            "operator": operator,
            "passed": passed,
        }
        if not passed:
            failures.append(f"{name} expected {operator} {threshold}, got {actual}")

    return EvaluationGateResult(
        passed=not failures,
        failures=failures,
        metrics=metrics,
    )


def gate_policy() -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "checks": DEFAULT_GATE_CHECKS,
    }


def gate_result_dict(result: EvaluationGateResult) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "failures": result.failures,
        "metrics": result.metrics,
        "policy_version": result.policy_version,
    }


def _passes(actual: Any, threshold: float | int, operator: str) -> bool:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        return False

    if operator == "eq":
        return value == float(threshold)
    if operator == "gte":
        return value >= float(threshold)
    return False
