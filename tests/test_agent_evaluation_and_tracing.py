from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app


def _client(tmp_path, monkeypatch, name: str = "agent-eval") -> TestClient:
    db_path = tmp_path / f"{name}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
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
    assert data["cases"][0]["trace_id"]
    assert {"response_quality", "trajectory_state", "efficiency"} <= set(data["cases"][0]["scores"])
    assert data["cases"][0]["llm_judge"]["mode"] in {"deterministic", "llm"}


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
