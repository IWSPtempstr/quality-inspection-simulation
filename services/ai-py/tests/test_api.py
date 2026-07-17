import asyncio

import httpx

from ai_service.api.app import create_app
from ai_service.conf.settings import Settings


def _request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, object] | None = None,
) -> httpx.Response:
    async def run() -> httpx.Response:
        app = create_app(Settings(service_bearer_token="test-token"))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, headers=headers, json=json)

    return asyncio.run(run())


def test_requires_authentication() -> None:
    response = _request(
        "POST",
        "/internal/v1/knowledge/query",
        json={"center_id": "c1", "actor_id": "a1", "query": "q"},
    )
    assert response.status_code == 401


def test_rejects_wrong_token() -> None:
    response = _request(
        "POST",
        "/internal/v1/knowledge/query",
        headers={"Authorization": "Bearer wrong"},
        json={"center_id": "c1", "actor_id": "a1", "query": "q"},
    )
    assert response.status_code == 403


def test_knowledge_query_returns_deterministic_placeholder() -> None:
    response = _request(
        "POST",
        "/internal/v1/knowledge/query",
        headers={"Authorization": "Bearer test-token"},
        json={"center_id": "c1", "actor_id": "a1", "query": "which standard"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "answer": "No cited standards are currently available for this query.",
        "citations": [],
        "evidence_available": False,
    }


def test_diagnosis_returns_structured_insufficient_result() -> None:
    response = _request(
        "POST",
        "/internal/v1/diagnoses",
        headers={"Authorization": "Bearer test-token"},
        json={
            "center_id": "c1",
            "actor_id": "a1",
            "event_id": "evt-1",
            "schedule_version": 2,
            "resource_snapshot_version": 3,
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "event_id": "evt-1",
        "affected_orders": [],
        "frozen_step_ids": [],
        "sla_risks": [],
        "affected_resources": [],
        "evidence": [],
        "resolved_case_ids": [],
        "recommendations": [],
        "evidence_gaps": ["Event snapshot was not provided."],
        "confidence": "insufficient",
        "degraded": True,
        "tool_calls": ["get_event_snapshot"],
    }


def test_diagnosis_returns_200_when_retrieval_is_degraded() -> None:
    response = _request(
        "POST",
        "/internal/v1/diagnoses",
        headers={"Authorization": "Bearer test-token"},
        json={
            "center_id": "c1",
            "actor_id": "a1",
            "event_id": "evt-2",
            "schedule_version": 2,
            "resource_snapshot_version": 3,
            "event_snapshot": {
                "event_type": "resource",
                "summary": "compressor outage",
                "affected_order_ids": ["order-1"],
                "equipment_ids": ["eq-1"],
                "project_codes": ["proj-a"],
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["degraded"] is True
    assert response.json()["tool_calls"] == [
        "get_event_snapshot",
        "get_order_snapshot",
        "get_schedule_snapshot",
        "search_standards",
        "search_resolved_cases",
    ]


def test_notification_draft_returns_degraded_placeholder() -> None:
    response = _request(
        "POST",
        "/internal/v1/notification-body-drafts",
        headers={"Authorization": "Bearer test-token", "X-Correlation-ID": "corr-1"},
        json={
            "center_id": "c1",
            "actor_id": "a1",
            "correlation_id": "corr-1",
            "notification_id": "n1",
            "title": "Title",
            "source_body": "secret body",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "body": "Notification drafting is not available in A1.",
        "degraded": True,
    }
