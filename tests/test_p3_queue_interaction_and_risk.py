from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from services.schedule_formatter import format_gantt, format_schedule_detail


def _schedule_fixture() -> dict:
    return {
        "id": "run-p3",
        "scheduled_count": 1,
        "blocked_count": 1,
        "created_at": "2026-06-01T09:00:00+08:00",
        "metrics": {},
        "steps": [
            {
                "id": "step-delayed",
                "run_id": "run-p3",
                "position": 1,
                "order_id": "order-delayed",
                "order_type": "vip",
                "sample_name": "延期样品",
                "certification_type": "ccc",
                "status": "scheduled",
                "step_kind": "detection",
                "project_id": "safety",
                "project_type": "safety_check",
                "equipment_type": "safety_tester",
                "equipment_id": "safety_tester-1",
                "lab_area": "safety_lab",
                "assigned_employee_ids": ["emp-1"],
                "resource_ids": [],
                "constraint_detail": {"operator_count": 1},
                "sequence": 1,
                "start_time": "2026-06-01T09:00:00+08:00",
                "end_time": "2026-06-01T11:00:00+08:00",
                "duration_minutes": 120,
                "arrival_time": "2026-06-01T08:00:00+08:00",
                "promised_finish_time": "2026-06-01T10:00:00+08:00",
                "sla_status": "delayed",
                "delay_minutes": 60,
                "execution_status": "scheduled",
                "locked": False,
            },
            {
                "id": "step-blocked",
                "run_id": "run-p3",
                "position": 2,
                "order_id": "order-blocked",
                "order_type": "urgent",
                "sample_name": "阻塞样品",
                "certification_type": "cvc",
                "status": "blocked",
                "blocked_reason": "required equipment, personnel or consumable unavailable: emc_tester",
            },
        ],
    }


def test_schedule_formatter_exposes_sla_and_blocked_reason_explanation():
    detail = format_schedule_detail(_schedule_fixture())
    gantt = format_gantt(_schedule_fixture())

    order = detail["scheduled_orders"][0]
    step = order["steps"][0]
    blocked = detail["blocked_orders"][0]
    bar = gantt["bars"][0]

    assert order["sla_risk_level"] == "delayed"
    assert step["sla_status"] == "delayed"
    assert step["delay_minutes"] == 60
    assert step["sla_risk_level"] == "delayed"
    assert bar["id"] == step["id"]
    assert bar["sla_status"] == "delayed"
    assert bar["delay_minutes"] == 60
    assert bar["sla_risk_level"] == "delayed"
    assert blocked["reason_detail"]["category"] == "resource_unavailable"
    assert "emc_tester" in blocked["reason_detail"]["summary"]
    assert blocked["reason_detail"]["suggested_action"]


def test_queue_page_contains_p3_interaction_and_risk_surfaces(tmp_path, monkeypatch):
    db_path = tmp_path / "p3-page.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    client = TestClient(create_app())

    response = client.get("/queue")

    assert response.status_code == 200
    assert "selected-step-detail" in response.text
    assert "阻塞原因解释" in response.text
    assert "SLA 风险" in response.text


def test_queue_static_assets_include_gantt_step_linkage_and_sla_classes():
    base_dir = Path(__file__).resolve().parents[1]
    app_js = (base_dir / "web" / "static" / "app.js").read_text(encoding="utf-8")
    css = (base_dir / "web" / "static" / "styles.css").read_text(encoding="utf-8")

    assert "highlightScheduleStep" in app_js
    assert "data-step-id" in app_js
    assert "aria-pressed" in app_js
    assert "renderBlockedReasonDetail" in app_js
    assert "slaClass" in app_js
    assert ".is-active-step" in css
    assert ".sla-delayed" in css
