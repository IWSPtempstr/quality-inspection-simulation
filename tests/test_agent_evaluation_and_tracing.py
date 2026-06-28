from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app
from db.repositories import AgentTraceRepository
from db.session import create_tables, get_session_factory
from services.evaluation_gate import evaluate_gate
from services.evaluation_service import AgentEvaluationService


def _client(tmp_path, monkeypatch, name: str = "agent-eval") -> TestClient:
    db_path = tmp_path / f"{name}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_PROFILE", "demo")
    monkeypatch.setenv("SCHEDULER_HEARTBEAT_ENABLED", "false")
    return TestClient(create_app())


def test_agent_run_persists_online_trace_with_steps(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "trace")

    response = client.post("/api/agent/run", json={"task_type": "query_queue", "payload": {}})
    trace_id = response.json()["data"]["trace"]["trace_id"]
    traces = client.get("/api/evaluation/traces")
    detail = client.get(f"/api/evaluation/traces/{trace_id}")

    assert response.status_code == 200
    assert trace_id
    assert response.json()["data"]["trace"]["latency_ms"] >= 0
    assert [step["agent_name"] for step in response.json()["data"]["trace"]["steps"]] == [
        "orchestrator",
        "queue_scheduler",
        "equipment_monitor",
    ]
    assert traces.status_code == 200
    assert any(item["trace_id"] == trace_id for item in traces.json()["data"]["items"])
    assert detail.status_code == 200
    assert detail.json()["data"]["task_type"] == "query_queue"
    assert detail.json()["data"]["steps"][0]["agent_name"] == "orchestrator"


def test_offline_evaluation_runs_jsonl_cases_and_scores_quality_path_efficiency(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "offline-eval")

    response = client.post(
        "/api/evaluation/offline/run",
        json={"dataset_path": "data/evaluation/agent_eval_cases.jsonl", "limit": 3},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["total_cases"] == 3
    assert data["summary"]["passed_cases"] >= 2
    assert data["summary"]["category_scores"]["trajectory_state"]["passed"] >= 2
    assert data["summary"]["category_scores"]["response_quality"]["total"] >= 3
    assert data["summary"]["category_scores"]["efficiency"]["total"] >= 3
    assert data["evaluation_gate"]["passed"] is True
    assert data["evaluation_gate"]["failures"] == []
    assert data["evaluation_gate"]["metrics"]["json_parse_success_rate"]["actual"] == data["summary"]["json_parse_success_rate"]
    assert "fallback_rate" in data["summary"]
    assert "write_auto_execute_count" in data["summary"]
    assert data["cases"][0]["trace_id"]
    assert {"response_quality", "trajectory_state", "efficiency"} <= set(data["cases"][0]["scores"])
    assert data["cases"][0]["llm_judge"]["mode"] in {"deterministic", "llm"}


def test_evaluation_gate_passes_when_present_metrics_meet_thresholds():
    result = evaluate_gate(
        {
            "fallback_success_rate": 1.0,
            "write_operation_violation_count": 0,
            "json_parse_success_rate": 0.95,
        }
    )

    assert result.passed is True
    assert result.failures == []
    assert set(result.metrics) == {
        "fallback_success_rate",
        "write_operation_violation_count",
        "json_parse_success_rate",
    }


def test_evaluation_gate_fails_when_present_metrics_miss_thresholds():
    result = evaluate_gate(
        {
            "fallback_success_rate": 0.5,
            "write_operation_violation_count": 1,
            "json_parse_success_rate": 0.94,
        }
    )

    assert result.passed is False
    assert len(result.failures) == 3
    assert "fallback_success_rate" in result.failures[0]
    assert "write_operation_violation_count" in result.failures[1]
    assert "json_parse_success_rate" in result.failures[2]


def test_evaluation_gate_ignores_missing_optional_metrics():
    result = evaluate_gate({"total_cases": 3})

    assert result.passed is True
    assert result.failures == []
    assert result.metrics == {}


def test_evaluation_gate_policy_and_check_api(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "gate-api")

    policy_response = client.get("/api/evaluation/gate/policy")
    check_response = client.post(
        "/api/evaluation/gate/check",
        json={
            "summary": {
                "pass_rate": 0.7,
                "route_accuracy": 0.8,
                "order_draft_field_accuracy": 0.9,
                "project_recommendation_recall": 1.0,
                "fallback_success_rate": 1.0,
                "write_operation_violation_count": 0,
                "json_parse_success_rate": 0.99,
            }
        },
    )

    assert policy_response.status_code == 200
    policy = policy_response.json()["data"]
    assert policy["policy_version"] == "harness-eval-gate-v2"
    assert "route_accuracy" in policy["checks"]
    assert check_response.status_code == 200
    gate = check_response.json()["data"]
    assert gate["passed"] is False
    assert any("pass_rate" in item for item in gate["failures"])
    assert gate["metrics"]["route_accuracy"]["passed"] is False


def test_evaluation_threshold_status_reports_alerts_from_traces(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "thresholds")

    for _ in range(2):
        client.post("/api/agent/run", json={"task_type": "query_queue", "payload": {}})

    response = client.get("/api/evaluation/thresholds/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["trace_count"] >= 2
    assert data["thresholds"]["agent_success_rate_min"] == 0.95
    assert "agent_success_rate" in data["metrics"]
    assert isinstance(data["alerts"], list)


def test_failed_trace_eval_records_exports_bounded_sanitized_regression_cases(tmp_path):
    session_factory = get_session_factory(f"sqlite:///{tmp_path / 'failed-traces.db'}")
    create_tables(session_factory)

    with session_factory() as session:
        repo = AgentTraceRepository(session)
        repo.create_trace(
            trace={
                "trace_id": "trace-success",
                "latency_ms": 1,
                "errors": [],
            },
            task_type="search_knowledge",
            payload_summary={"query": "safe but successful"},
        )
        repo.create_trace(
            trace={
                "trace_id": "trace-old",
                "latency_ms": 1,
                "errors": [{"message": "older failure"}],
            },
            task_type="explain_schedule",
            payload_summary={"query": "old safe value"},
        )
        repo.create_trace(
            trace={
                "trace_id": "trace-new",
                "latency_ms": 1,
                "errors": [{"message": "new failure"}],
                "tool_calls": [{"body": {"prompt": "raw prompt"}}],
            },
            task_type="route_user_query",
            payload_summary={
                "user_query": "show delayed orders",
                "api_key": "sk-secret",
                "prompt": "raw prompt",
                "tool_call_body": {"args": ["unsafe"]},
                "large_blob": "x" * 1000,
                "nested": {"token": "secret"},
            },
        )

    service = AgentEvaluationService(session_factory=session_factory, base_dir=tmp_path, agent_graph=None)

    assert service.failed_trace_eval_records(limit=1) == [
        {
            "case_id": "trace:trace-new",
            "task_type": "route_user_query",
            "payload": {"user_query": "show delayed orders"},
            "expected": {
                "regression_source": "online_trace",
                "failure_reason": "new failure",
            },
        }
    ]


def test_failed_trace_eval_records_uses_empty_payload_when_summary_is_not_safe(tmp_path):
    session_factory = get_session_factory(f"sqlite:///{tmp_path / 'unsafe-traces.db'}")
    create_tables(session_factory)

    with session_factory() as session:
        AgentTraceRepository(session).create_trace(
            trace={
                "trace_id": "trace-unsafe",
                "latency_ms": 1,
                "errors": [{"error": "contains only unsafe payload"}],
            },
            task_type="draft_order_from_text",
            payload_summary={
                "messages": [{"role": "user", "content": "raw prompt"}],
                "authorization": "Bearer secret",
                "request_body": {"sample": "unsafe"},
            },
        )

    service = AgentEvaluationService(session_factory=session_factory, base_dir=tmp_path, agent_graph=None)

    assert service.failed_trace_eval_records() == [
        {
            "case_id": "trace:trace-unsafe",
            "task_type": "draft_order_from_text",
            "payload": {},
            "expected": {
                "regression_source": "online_trace",
                "failure_reason": "contains only unsafe payload",
            },
        }
    ]


def test_failed_trace_eval_records_api_supports_json_and_jsonl(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "failed-trace-api")
    with client.app.state.session_factory() as session:
        AgentTraceRepository(session).create_trace(
            trace={
                "trace_id": "trace-api-failed",
                "latency_ms": 1,
                "errors": [{"message": "api failure"}],
            },
            task_type="route_user_query",
            payload_summary={"user_query": "show delayed orders", "prompt": "raw"},
        )

    json_response = client.get(
        "/api/evaluation/failed-traces/eval-records",
        params={"task_type": "route_user_query", "limit": 5},
    )
    jsonl_response = client.get(
        "/api/evaluation/failed-traces/eval-records",
        params={"format": "jsonl"},
    )

    assert json_response.status_code == 200
    data = json_response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["case_id"] == "trace:trace-api-failed"
    assert data["items"][0]["payload"] == {"user_query": "show delayed orders"}
    assert jsonl_response.status_code == 200
    assert jsonl_response.json()["data"]["format"] == "jsonl"
    assert '"case_id": "trace:trace-api-failed"' in jsonl_response.json()["data"]["content"]
