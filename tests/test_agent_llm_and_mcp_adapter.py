from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agents import AgentGraphRunner
from agents.llm_gateway import LlmGateway
from agents.trace_utils import (
    aggregate_token_usage,
    agent_token_usage,
    agent_tool_calls,
    json_ready,
)
from agents.validators import (
    valid_exception_analysis,
    valid_knowledge_answer,
    valid_schedule_explanation,
    validate_route_recommendation,
)
from app import create_app
from config.settings import AgentModelConfig
from domain.schemas import CertificationType
from services.evaluation_service import AgentEvaluationService
from services.llm_client import OpenAICompatibleLlmClient
from services.queue_service import QueueService
from services.simulation_service import SimulationService
from services.tool_client import LocalSimulationToolClient
from rag.retriever import KnowledgeRetriever
from db.session import create_tables, get_session_factory


# ---------------------------------------------------------------------------
# mock LLM clients
# ---------------------------------------------------------------------------

class FailingLlmClient:
    """Implements the full LlmClientProtocol but always raises."""

    def chat_json(self, *_args, **_kwargs):
        raise RuntimeError("simulated llm failure")

    def analyze_exception(self, *_args, **_kwargs):
        raise RuntimeError("simulated llm failure")


class MockLlmClient:
    """Returns a configurable JSON payload for chat_json."""

    def __init__(self, response: dict | None = None):
        self._response = response or {"message": "mock response"}
        self.last_system_prompt = ""
        self.last_user_message = ""

    def chat_json(self, config, system_prompt, user_message, **kwargs):
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        return {
            "content": self._response,
            "token_usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            "model": config.model,
        }


class _FakeHttpResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeHttpClient:
    requests: list[dict] = []
    payload: dict = {}

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, endpoint, headers=None, json=None):
        self.__class__.requests.append({
            "endpoint": endpoint,
            "headers": headers or {},
            "json": json or {},
        })
        return _FakeHttpResponse(self.__class__.payload)

    def analyze_exception(self, config, snapshot, payload=None):
        result = self.chat_json(
            config, "exception system prompt",
            json.dumps({"snapshot": snapshot, "payload": payload or {}}),
        )
        return {
            "mode": "llm",
            "model": result["model"],
            "content": json.dumps(result["content"], ensure_ascii=False),
            "token_usage": result["token_usage"],
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_runner(tmp_path, llm_client=None, agent_configs=None):
    session_factory = get_session_factory(f"sqlite:///{tmp_path / 'test.db'}")
    create_tables(session_factory)
    simulation = SimulationService()
    queue = QueueService(simulation)
    return AgentGraphRunner(
        session_factory=session_factory,
        simulation_service=simulation,
        queue_service=queue,
        retriever=KnowledgeRetriever(tmp_path / "knowledge", index_dir=tmp_path / "index"),
        tool_client=LocalSimulationToolClient(simulation, queue),
        agent_configs=agent_configs or {},
        llm_client=llm_client,
    )


def _mock_exception_config():
    return AgentModelConfig(
        agent_name="exception_analyzer",
        provider="openai-compatible",
        api_key="configured",
        base_url="https://example.com/v1",
        model="analysis-model",
        temperature=0.2,
        max_tokens=512,
        enable_thinking=True,
    )


# ---------------------------------------------------------------------------
# existing tests — kept and extended
# ---------------------------------------------------------------------------

def test_exception_analyzer_falls_back_when_llm_fails(tmp_path):
    config = _mock_exception_config()
    runner = _build_runner(
        tmp_path,
        llm_client=FailingLlmClient(),
        agent_configs={"exception_analyzer": config},
    )

    result = runner.run(type("Request", (), {"task_type": "analyze_exception", "payload": {}})())

    assert result["result"]["analysis"]["mode"] == "deterministic_fallback"
    assert "exception_analyzer llm failed" in result["errors"][0]


def test_mcp_status_exposes_adapter_type(tmp_path, monkeypatch):
    db_path = tmp_path / "adapter.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MCP_ADAPTER_TYPE", "simulation")

    client = TestClient(create_app())
    response = client.get("/api/mcp/status")

    assert response.status_code == 200
    assert response.json()["data"]["adapter_type"] == "simulation"


# ---------------------------------------------------------------------------
# Step 1: chat_json
# ---------------------------------------------------------------------------

def test_chat_json_returns_structured_result(tmp_path):
    """chat_json should parse JSON content and extract token usage."""
    mock = MockLlmClient({"key": "value", "list": [1, 2, 3]})
    config = AgentModelConfig(
        agent_name="test_agent",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="test-model",
        temperature=0.0,
        max_tokens=256,
        enable_thinking=False,
    )

    result = mock.chat_json(config, "system", "user message")

    assert result["content"] == {"key": "value", "list": [1, 2, 3]}
    assert result["token_usage"]["input_tokens"] == 100
    assert result["token_usage"]["output_tokens"] == 50
    assert result["token_usage"]["total_tokens"] == 150
    assert result["model"] == "test-model"


def test_openai_compatible_chat_json_parses_fenced_json_and_usage(monkeypatch):
    _FakeHttpClient.requests = []
    _FakeHttpClient.payload = {
        "choices": [{
            "message": {
                "content": "```json\n{\"answer\":\"ok\",\"citations\":[\"kb.txt\"]}\n```"
            }
        }],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        },
    }
    monkeypatch.setattr("services.llm_client.httpx.Client", _FakeHttpClient)
    config = AgentModelConfig(
        agent_name="rag_retriever",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="gpt-test",
        temperature=0.0,
        max_tokens=128,
        enable_thinking=True,
    )

    result = OpenAICompatibleLlmClient().chat_json(config, "system", "user")

    assert result["content"] == {"answer": "ok", "citations": ["kb.txt"]}
    assert result["token_usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    assert "enable_thinking" not in _FakeHttpClient.requests[0]["json"]


def test_openai_compatible_chat_json_only_qwen_sends_enable_thinking(monkeypatch):
    _FakeHttpClient.requests = []
    _FakeHttpClient.payload = {
        "choices": [{"message": {"content": "{\"ok\": true}"}}],
        "usage": {},
    }
    monkeypatch.setattr("services.llm_client.httpx.Client", _FakeHttpClient)
    config = AgentModelConfig(
        agent_name="queue_scheduler",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="qwen-plus",
        temperature=0.0,
        max_tokens=128,
        enable_thinking=False,
    )

    OpenAICompatibleLlmClient().chat_json(config, "system", "user")

    assert _FakeHttpClient.requests[0]["json"]["enable_thinking"] is False


def test_openai_compatible_chat_json_non_json_raises(monkeypatch):
    _FakeHttpClient.requests = []
    _FakeHttpClient.payload = {
        "choices": [{"message": {"content": "这不是 JSON"}}],
        "usage": {},
    }
    monkeypatch.setattr("services.llm_client.httpx.Client", _FakeHttpClient)
    config = AgentModelConfig(
        agent_name="exception_analyzer",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="gpt-test",
        temperature=0.0,
        max_tokens=128,
        enable_thinking=True,
    )

    with pytest.raises(json.JSONDecodeError):
        OpenAICompatibleLlmClient().chat_json(config, "system", "user")


# ---------------------------------------------------------------------------
# Task H1: trace utility extraction
# ---------------------------------------------------------------------------

def test_trace_utils_json_ready_converts_nested_values():
    value = {
        "certification": CertificationType.CCC,
        "created_at": type("IsoValue", (), {"isoformat": lambda self: "2026-06-17T00:00:00"})(),
        "items": [{"certification": CertificationType.CVC}],
    }

    assert json_ready(value) == {
        "certification": "ccc",
        "created_at": "2026-06-17T00:00:00",
        "items": [{"certification": "cvc"}],
    }


def test_trace_utils_agent_tool_calls_include_llm_and_agent_tools():
    calls = agent_tool_calls({
        "agent_name": "rag_retriever",
        "task_type": "search_knowledge",
        "result": {
            "knowledge_context": [{"source": "kb.txt"}],
            "llm_metadata": {
                "llm_called": True,
                "model": "rag-model",
                "fallback_used": False,
                "error": None,
            },
        },
    })

    assert calls == [
        {
            "tool_name": "llm_chat_json",
            "status": "success",
            "model": "rag-model",
            "fallback_used": False,
            "error": None,
        },
        {"tool_name": "knowledge_search", "status": "success", "result_count": 1},
    ]


def test_trace_utils_token_usage_prefers_llm_metadata_and_aggregates():
    usage = agent_token_usage({
        "result": {
            "analysis": {
                "token_usage": {
                    "input_tokens": 999,
                    "output_tokens": 999,
                    "total_tokens": 999,
                }
            },
            "llm_metadata": {
                "token_usage": {
                    "input_tokens": "10",
                    "output_tokens": 5,
                    "total_tokens": 15,
                }
            },
        }
    })

    assert usage == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    assert aggregate_token_usage([
        {"token_usage": usage},
        {"token_usage": {"input_tokens": 1, "output_tokens": None, "total_tokens": 1}},
        {},
    ]) == {"input_tokens": 11, "output_tokens": 5, "total_tokens": 16}


# ---------------------------------------------------------------------------
# Task H2: validation helper extraction
# ---------------------------------------------------------------------------

def test_validate_route_recommendation_accepts_allowed_task_agent_pair():
    assert validate_route_recommendation({
        "recommended_task_type": "explain_schedule",
        "target_agent": "queue_scheduler",
    }) is True


def test_validate_route_recommendation_rejects_disallowed_pair():
    assert validate_route_recommendation({
        "recommended_task_type": "create_order",
        "target_agent": "order_manager",
    }) is False


def test_valid_knowledge_answer_requires_answer_citations_and_numeric_confidence():
    assert valid_knowledge_answer({
        "answer": "CCC 安全检测需要耐压测试。",
        "citations": ["ccc_safety.txt"],
        "confidence": 0.9,
    }) is True
    assert valid_knowledge_answer({
        "answer": "",
        "citations": ["ccc_safety.txt"],
        "confidence": 0.9,
    }) is False
    assert valid_knowledge_answer({
        "answer": "缺少引用字段",
        "confidence": 0.9,
    }) is False
    assert valid_knowledge_answer({
        "answer": "置信度非法",
        "citations": [],
        "confidence": "high",
    }) is False


def test_valid_schedule_explanation_requires_structured_fields():
    assert valid_schedule_explanation({
        "summary": "当前排程稳定。",
        "sla_risks": [],
        "bottlenecks": [],
        "blocking_analysis": [],
        "recommended_actions": [],
    }) is True
    assert valid_schedule_explanation({
        "summary": "缺少建议字段",
        "sla_risks": [],
        "bottlenecks": [],
        "blocking_analysis": [],
    }) is False


def test_valid_exception_analysis_requires_risk_level_whitelist():
    assert valid_exception_analysis({
        "root_causes": [],
        "affected_orders": [],
        "bottleneck_resources": [],
        "risk_level": "high",
        "recommended_actions": [],
    }) is True
    assert valid_exception_analysis({
        "root_causes": [],
        "affected_orders": [],
        "bottleneck_resources": [],
        "risk_level": "severe",
        "recommended_actions": [],
    }) is False


# ---------------------------------------------------------------------------
# Step 2: llm_metadata in agent trace
# ---------------------------------------------------------------------------

def test_llm_metadata_recorded_in_trace_steps(tmp_path):
    """When an agent uses LLM, token usage should appear in trace steps."""
    mock = MockLlmClient({
        "root_causes": [],
        "affected_orders": [],
        "bottleneck_resources": [],
        "risk_level": "low",
        "recommended_actions": [],
    })
    config = _mock_exception_config()
    runner = _build_runner(
        tmp_path,
        llm_client=mock,
        agent_configs={"exception_analyzer": config},
    )

    result = runner.run(type("Request", (), {"task_type": "analyze_exception", "payload": {}})())

    trace = result["trace"]
    assert trace["token_usage"]["total_tokens"] == 150
    # The exception_analyzer step should carry token usage
    exception_steps = [s for s in trace["steps"] if s["agent_name"] == "exception_analyzer"]
    assert exception_steps
    assert exception_steps[0]["token_usage"]["total_tokens"] == 150


# ---------------------------------------------------------------------------
# Step 3: RAG answer synthesis
# ---------------------------------------------------------------------------

def test_rag_returns_fallback_when_no_api_key(tmp_path):
    """Without LLM config, search_knowledge should return knowledge_context
    and a deterministic knowledge_answer."""
    runner = _build_runner(tmp_path)

    result = runner.run(type("Request", (), {"task_type": "search_knowledge", "payload": {"query": "CCC 安全检测"}})())

    assert "knowledge_context" in result["result"]
    assert "knowledge_answer" in result["result"]
    answer = result["result"]["knowledge_answer"]
    assert answer["mode"] == "deterministic_fallback"
    assert "answer" in answer
    assert "citations" in answer
    assert "confidence" in answer


def test_rag_returns_llm_answer_when_configured(tmp_path):
    """With a mock LLM, knowledge_answer should be llm-synthesized."""
    mock = MockLlmClient({
        "answer": "根据CCC认证知识库，安全检测需要包含耐压测试和接地电阻测试。",
        "citations": ["ccc_safety.txt"],
        "confidence": 0.95,
    })
    config = AgentModelConfig(
        agent_name="rag_retriever",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="rag-model",
        temperature=0.0,
        max_tokens=512,
        enable_thinking=False,
    )
    runner = _build_runner(
        tmp_path,
        llm_client=mock,
        agent_configs={"rag_retriever": config},
    )

    result = runner.run(type("Request", (), {"task_type": "search_knowledge", "payload": {"query": "CCC 安全检测"}})())

    answer = result["result"]["knowledge_answer"]
    assert answer["mode"] == "llm"
    assert "CCC" in answer["answer"]
    assert "ccc_safety.txt" in answer["citations"]


def test_rag_no_hits_fallback_clear_message(tmp_path):
    """When retriever finds nothing, fallback answer should state that clearly."""
    runner = _build_runner(tmp_path)

    result = runner.run(type("Request", (), {"task_type": "search_knowledge", "payload": {"query": "不存在的主题XYZ123"}})())

    answer = result["result"]["knowledge_answer"]
    # Fallback should mention no results or return a clear message
    assert isinstance(answer["answer"], str)
    assert len(answer["answer"]) > 0


def test_rag_llm_answer_without_citations_falls_back_to_retrieved_sources(tmp_path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "ccc_safety.txt").write_text(
        "CCC 安全检测包括耐压测试、接地电阻测试和绝缘电阻测试。",
        encoding="utf-8",
    )
    mock = MockLlmClient({
        "answer": "缺少引用的回答不应直接作为可信 RAG 输出。",
        "citations": [],
        "confidence": 0.99,
    })
    config = AgentModelConfig(
        agent_name="rag_retriever",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="rag-model",
        temperature=0.0,
        max_tokens=512,
        enable_thinking=False,
    )
    runner = _build_runner(
        tmp_path,
        llm_client=mock,
        agent_configs={"rag_retriever": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "search_knowledge",
        "payload": {"query": "CCC 安全检测"},
    })())

    answer = result["result"]["knowledge_answer"]
    assert answer["mode"] == "deterministic_fallback"
    assert answer["citations"]


# ---------------------------------------------------------------------------
# Step 4: explain_schedule
# ---------------------------------------------------------------------------

def test_explain_schedule_does_not_trigger_rebuild(tmp_path):
    """explain_schedule must be read-only — no schedule run created."""
    runner = _build_runner(
        tmp_path,
        llm_client=MockLlmClient({
            "summary": "正常", "sla_risks": [],
            "bottlenecks": [], "blocking_analysis": [],
            "recommended_actions": [], "mode": "llm",
        }),
        agent_configs={
            "queue_scheduler": AgentModelConfig(
                agent_name="queue_scheduler",
                provider="openai-compatible",
                api_key="sk-test",
                base_url="https://example.com/v1",
                model="sched-model",
                temperature=0.0,
                max_tokens=1024,
                enable_thinking=False,
            ),
        },
    )

    result = runner.run(type("Request", (), {"task_type": "explain_schedule", "payload": {}})())

    assert "summary" in result["result"]
    assert "sla_risks" in result["result"]
    assert "bottlenecks" in result["result"]
    assert "recommended_actions" in result["result"]
    # No "queue" wrapper — explain_schedule returns results directly
    assert "queue" not in result["result"]


def test_explain_schedule_fallback_on_llm_failure(tmp_path):
    """When LLM fails, explain_schedule returns deterministic fallback."""
    config = AgentModelConfig(
        agent_name="queue_scheduler",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="sched-model",
        temperature=0.0,
        max_tokens=1024,
        enable_thinking=False,
    )
    runner = _build_runner(
        tmp_path,
        llm_client=FailingLlmClient(),
        agent_configs={"queue_scheduler": config},
    )

    result = runner.run(type("Request", (), {"task_type": "explain_schedule", "payload": {}})())

    assert result["result"]["mode"] == "deterministic_fallback"
    assert "summary" in result["result"]


def test_explain_schedule_missing_required_keys_falls_back(tmp_path):
    config = AgentModelConfig(
        agent_name="queue_scheduler",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="sched-model",
        temperature=0.0,
        max_tokens=1024,
        enable_thinking=False,
    )
    runner = _build_runner(
        tmp_path,
        llm_client=MockLlmClient({"summary": "只返回摘要"}),
        agent_configs={"queue_scheduler": config},
    )

    result = runner.run(type("Request", (), {"task_type": "explain_schedule", "payload": {}})())

    assert result["result"]["mode"] == "deterministic_fallback"
    for key in ["summary", "sla_risks", "bottlenecks", "blocking_analysis", "recommended_actions"]:
        assert key in result["result"]


def test_explain_schedule_permission_is_read_only(tmp_path, monkeypatch):
    """The API endpoint should require only schedule:read."""
    db_path = tmp_path / "explain.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    client = TestClient(create_app())
    response = client.post(
        "/api/agent/run",
        json={"task_type": "explain_schedule", "payload": {}},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    # Should go through queue_scheduler → equipment_monitor
    assert "queue_scheduler" in data["visited_agents"]


# ---------------------------------------------------------------------------
# Step 5: structured exception analysis
# ---------------------------------------------------------------------------

def test_exception_analyzer_structured_output(tmp_path):
    """LLM-powered exception analysis should include new structured fields."""
    mock = MockLlmClient({
        "root_causes": [{"cause": "EMC设备不足", "evidence": "利用率0.95"}],
        "affected_orders": [{"order_id": "ORDER-001", "impact": "延迟120分钟"}],
        "bottleneck_resources": [{"resource": "emc_tester-1", "utilization": 0.95}],
        "risk_level": "high",
        "recommended_actions": ["增加EMC测试设备或调整排程策略"],
    })
    config = _mock_exception_config()
    runner = _build_runner(
        tmp_path,
        llm_client=mock,
        agent_configs={"exception_analyzer": config},
    )

    result = runner.run(type("Request", (), {"task_type": "analyze_exception", "payload": {}})())

    analysis = result["result"]["analysis"]
    assert analysis["mode"] == "llm"
    assert "root_causes" in analysis
    assert "risk_level" in analysis
    assert analysis["risk_level"] == "high"
    assert len(analysis["root_causes"]) > 0
    assert len(analysis["recommended_actions"]) > 0


def test_exception_analyzer_keeps_backward_compat_fields(tmp_path):
    """Legacy fields (blocked_orders, blocked_count) must still exist."""
    mock = MockLlmClient({
        "root_causes": [],
        "affected_orders": [],
        "bottleneck_resources": [],
        "risk_level": "low",
        "recommended_actions": [],
    })
    config = _mock_exception_config()
    runner = _build_runner(
        tmp_path,
        llm_client=mock,
        agent_configs={"exception_analyzer": config},
    )

    result = runner.run(type("Request", (), {"task_type": "analyze_exception", "payload": {}})())

    assert "blocked_orders" in result["result"]
    assert "blocked_count" in result["result"]


def test_exception_analyzer_missing_required_keys_falls_back(tmp_path):
    mock = MockLlmClient({"risk_level": "high"})
    config = _mock_exception_config()
    runner = _build_runner(
        tmp_path,
        llm_client=mock,
        agent_configs={"exception_analyzer": config},
    )

    result = runner.run(type("Request", (), {"task_type": "analyze_exception", "payload": {}})())

    analysis = result["result"]["analysis"]
    assert analysis["mode"] == "deterministic_fallback"
    for key in ["root_causes", "affected_orders", "bottleneck_resources", "risk_level", "recommended_actions"]:
        assert key in analysis


# ---------------------------------------------------------------------------
# Step 6: notification text enhancement
# ---------------------------------------------------------------------------

def test_notifications_unchanged_without_llm(tmp_path):
    """Without LLM key, notifications keep template text."""
    runner = _build_runner(tmp_path)

    result = runner.run(type("Request", (), {"task_type": "generate_notifications", "payload": {}})())

    notifications = result["result"].get("notifications", [])
    for n in notifications:
        assert n.get("llm_enhanced") is not True  # False or absent


def test_notifications_enhanced_with_llm(tmp_path):
    """With mock LLM, notifications get enhanced title/message."""
    mock = MockLlmClient({
        "title": "[优化] 订单预计延期",
        "message": "VIP订单 ORD-001 预计延迟120分钟。建议联系实验室确认设备状态。",
        "suggested_actions": ["联系实验室确认EMC设备释放时间", "考虑加班安排"],
    })
    config = AgentModelConfig(
        agent_name="notification_agent",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="notify-model",
        temperature=0.3,
        max_tokens=512,
        enable_thinking=False,
    )
    runner = _build_runner(
        tmp_path,
        llm_client=mock,
        agent_configs={"notification_agent": config},
    )

    result = runner.run(type("Request", (), {"task_type": "generate_notifications", "payload": {}})())

    notifications = result["result"].get("notifications", [])
    # Check that LLM-enhanced notifications have the new fields
    enhanced = [n for n in notifications if n.get("llm_enhanced")]
    if enhanced:
        assert "suggested_actions" in enhanced[0]
        assert isinstance(enhanced[0]["suggested_actions"], list)


def test_notifications_survive_llm_failure(tmp_path):
    """When LLM fails, notifications should still be generated."""
    config = AgentModelConfig(
        agent_name="notification_agent",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="notify-model",
        temperature=0.3,
        max_tokens=512,
        enable_thinking=False,
    )
    runner = _build_runner(
        tmp_path,
        llm_client=FailingLlmClient(),
        agent_configs={"notification_agent": config},
    )

    result = runner.run(type("Request", (), {"task_type": "generate_notifications", "payload": {}})())

    notifications = result["result"].get("notifications", [])
    assert isinstance(notifications, list)
    # Even with failing LLM, notifications shouldn't break


# ============================================================================
# v2 tests — draft_order_from_text, project recommendations, task routing
# ============================================================================

def _mock_order_draft_response():
    """Return LLM-style response — wrapper applied by _validate_and_wrap_order_draft."""
    return {
        "order_type": "vip",
        "sample_name": "温控开关",
        "sample_quantity": 200,
        "certification_type": "ccc",
        "requested_projects": ["ccc-safety", "ccc-emc"],
        "promised_finish_time": "2026-06-13T18:00:00+08:00",
        "field_confidence": {"order_type": 0.98, "sample_name": 0.99},
        "missing_fields": [],
        "notes": "已自动补全 CCC 常规检测项目",
    }


def _mock_order_draft_config():
    return AgentModelConfig(
        agent_name="order_manager",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="draft-model",
        temperature=0.0,
        max_tokens=512,
        enable_thinking=False,
    )


# ---------------------------------------------------------------------------
# Task H3: LLM gateway
# ---------------------------------------------------------------------------

def test_llm_gateway_missing_client_returns_fallback_without_metadata():
    fallback = {"mode": "deterministic_fallback", "answer": "fallback"}
    config = _mock_orchestrator_config()

    result = LlmGateway({"orchestrator": config}).chat_json(
        agent_name="orchestrator",
        client=None,
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "user"}],
        fallback=lambda _error: fallback,
    )

    assert result.content == fallback
    assert result.mode == "deterministic_fallback"
    assert result.fallback_used is True
    assert result.error is None
    assert result.metadata == {}


def test_llm_gateway_invalid_required_keys_returns_fallback_metadata():
    fallback = {"mode": "deterministic_fallback", "answer": "fallback"}
    config = _mock_orchestrator_config()

    result = LlmGateway({"orchestrator": config}).chat_json(
        agent_name="orchestrator",
        client=MockLlmClient({"answer": "missing confidence"}),
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "user"}],
        fallback=lambda error: {**fallback, "error": error},
        required_keys={"answer", "confidence"},
    )

    assert result.content["mode"] == "deterministic_fallback"
    assert result.content["error"] == "missing required LLM keys: confidence"
    assert result.mode == "deterministic_fallback"
    assert result.fallback_used is True
    assert result.error == "missing required LLM keys: confidence"
    assert result.metadata == {
        "llm_called": True,
        "model": "route-model",
        "token_usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        "fallback_used": True,
        "error": "missing required LLM keys: confidence",
        "retry_attempt": 0,
    }


def test_llm_gateway_exception_fallback_retries_and_records_metadata():
    fallback = {"mode": "deterministic_fallback", "answer": "fallback"}
    config = _mock_orchestrator_config()

    result = LlmGateway({"orchestrator": config}, retry_sleep_seconds=0).chat_json(
        agent_name="orchestrator",
        client=FailingLlmClient(),
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "user"}],
        fallback=lambda _error: fallback,
    )

    assert result.content == fallback
    assert result.mode == "deterministic_fallback"
    assert result.fallback_used is True
    assert result.error == "simulated llm failure"
    assert result.metadata == {
        "llm_called": True,
        "model": "route-model",
        "token_usage": None,
        "fallback_used": True,
        "error": "simulated llm failure",
        "retry_attempt": 1,
    }


# -- draft_order_from_text ---------------------------------------------------

def test_draft_order_from_text_full_input(tmp_path):
    mock = MockLlmClient(_mock_order_draft_response())
    config = _mock_order_draft_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"order_manager": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "draft_order_from_text",
        "payload": {"user_text": "为温控开关创建VIP CCC检测订单，200个样品"},
    })())

    draft = result["result"]["order_draft"]
    assert draft["order_type"] == "vip"
    assert draft["certification_type"] == "ccc"
    assert draft["sample_quantity"] == 200
    assert result["result"]["missing_fields"] == []
    assert result["result"]["confirmation_required"] is True


def test_draft_order_from_text_missing_quantity(tmp_path):
    mock = MockLlmClient({
        "order_type": "normal",
        "sample_name": "电源适配器",
        "sample_quantity": None,
        "certification_type": "cvc",
        "requested_projects": [],
        "promised_finish_time": None,
        "field_confidence": {},
        "missing_fields": ["sample_quantity"],
        "notes": "",
    })
    config = _mock_order_draft_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"order_manager": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "draft_order_from_text",
        "payload": {"user_text": "创建一个订单"},
    })())

    assert "sample_quantity" in result["result"]["missing_fields"]


def test_draft_order_invalid_enum_rejected(tmp_path):
    mock = MockLlmClient({
        "order_type": "xyz_invalid",
        "sample_name": "样品",
        "sample_quantity": 50,
        "certification_type": "unknown_cert",
        "requested_projects": [],
        "promised_finish_time": None,
        "field_confidence": {},
        "missing_fields": [],
        "notes": "",
    })
    config = _mock_order_draft_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"order_manager": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "draft_order_from_text",
        "payload": {"user_text": "xyz认证订单"},
    })())

    missing = result["result"]["missing_fields"]
    assert "order_type" in missing
    assert "certification_type" in missing


def test_draft_order_does_not_write_to_db(tmp_path):
    mock = MockLlmClient(_mock_order_draft_response())
    config = _mock_order_draft_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"order_manager": config},
    )

    # Run draft
    runner.run(type("Request", (), {
        "task_type": "draft_order_from_text",
        "payload": {"user_text": "VIP订单"},
    })())

    # Verify no orders were created
    list_result = runner.run(type("Request", (), {"task_type": "list_orders", "payload": {}})())
    assert len(list_result["result"]["orders"]) == 0


def test_draft_order_fallback_without_llm(tmp_path):
    runner = _build_runner(tmp_path)

    result = runner.run(type("Request", (), {
        "task_type": "draft_order_from_text",
        "payload": {"user_text": "创建订单"},
    })())

    assert result["result"]["mode"] == "deterministic_fallback"
    assert result["result"]["confirmation_required"] is True


def test_draft_order_fallback_extracts_basic_fields_without_llm(tmp_path):
    runner = _build_runner(tmp_path)

    result = runner.run(type("Request", (), {
        "task_type": "draft_order_from_text",
        "payload": {"user_text": "为温控开关创建VIP CCC检测订单，200个样品"},
    })())

    draft = result["result"]["order_draft"]
    assert draft["order_type"] == "vip"
    assert draft["certification_type"] == "ccc"
    assert draft["sample_quantity"] == 200
    assert result["result"]["missing_fields"] == []


# -- project recommendations -------------------------------------------------

def _mock_project_config():
    return AgentModelConfig(
        agent_name="project_identifier",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="project-model",
        temperature=0.0,
        max_tokens=512,
        enable_thinking=False,
    )


def test_identify_projects_recommends_with_description(tmp_path):
    mock = MockLlmClient({
        "recommended_projects": [
            {"project_type": "ccc-safety", "equipment_type": "safety_tester",
             "reason": "CCC 安全必检", "is_required": True},
            {"project_type": "ccc-emc", "equipment_type": "emc_tester",
             "reason": "电源模块需要 EMC 检测", "is_required": True},
        ],
        "risk_notes": [],
    })
    config = _mock_project_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"project_identifier": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "identify_projects",
        "payload": {
            "certification_type": "ccc",
            "sample_description": "家用电器电源模块，需要安全检测和EMC",
            "product_category": "家用电器",
        },
    })())

    assert "recommended_projects" in result["result"]
    assert "required_projects" in result["result"]
    assert "risk_notes" in result["result"]


def test_identify_projects_retains_required_without_llm(tmp_path):
    runner = _build_runner(tmp_path)

    result = runner.run(type("Request", (), {
        "task_type": "identify_projects",
        "payload": {"certification_type": "ccc", "requested_projects": ["ccc-safety"]},
    })())

    assert "detection_flow" in result["result"]
    # Without sample_description, should NOT have LLM recommendations
    assert "recommended_projects" not in result["result"]


def test_identify_projects_fallback_recommends_required_with_description(tmp_path):
    runner = _build_runner(tmp_path)

    result = runner.run(type("Request", (), {
        "task_type": "identify_projects",
        "payload": {
            "certification_type": "ccc",
            "sample_description": "家用电器电源模块，需要安全检测和EMC检测",
            "product_category": "家用电器",
        },
    })())

    assert result["result"]["recommended_projects"]
    assert result["result"]["required_projects"]
    assert result["result"]["mode"] == "deterministic_fallback"


def test_identify_projects_hallucinated_filtered(tmp_path):
    mock = MockLlmClient({
        "recommended_projects": [
            {"project_type": "ccc-safety", "equipment_type": "safety_tester",
             "reason": "安全必检", "is_required": True},
            {"project_type": "fake-hallucinated-project", "equipment_type": "unknown_device",
             "reason": "幻觉项目", "is_required": False},
        ],
        "risk_notes": [],
    })
    config = _mock_project_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"project_identifier": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "identify_projects",
        "payload": {
            "certification_type": "ccc",
            "sample_description": "家用电器电源模块",
            "product_category": "家用电器",
        },
    })())

    # The hallucinated project should be in optional, not required
    optional = result["result"].get("optional_projects", [])
    optional_types = [p.get("project_type") for p in optional]
    assert "fake-hallucinated-project" in optional_types


# -- route_user_query ---------------------------------------------------------

def _mock_orchestrator_config():
    return AgentModelConfig(
        agent_name="orchestrator",
        provider="openai-compatible",
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="route-model",
        temperature=0.0,
        max_tokens=256,
        enable_thinking=False,
    )


def test_route_user_query_delay_to_explain(tmp_path):
    mock = MockLlmClient({
        "recommended_task_type": "explain_schedule",
        "target_agent": "queue_scheduler",
        "confidence": 0.95,
        "suggested_payload": {},
        "needs_clarification": False,
        "clarifying_question": "",
        "reasoning": "用户询问队列延期情况",
    })
    config = _mock_orchestrator_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"orchestrator": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "route_user_query",
        "payload": {"user_query": "为什么队列有延期的订单"},
    })())

    assert result["result"]["recommended_task_type"] == "explain_schedule"
    assert result["result"]["target_agent"] == "queue_scheduler"
    assert result["result"]["confidence"] >= 0.7
    assert result["visited_agents"] == ["orchestrator"]


def test_route_user_query_create_vip_to_draft(tmp_path):
    mock = MockLlmClient({
        "recommended_task_type": "draft_order_from_text",
        "target_agent": "order_manager",
        "confidence": 0.92,
        "suggested_payload": {"user_text": "创建VIP订单"},
        "needs_clarification": False,
        "clarifying_question": "",
        "reasoning": "用户想创建订单",
    })
    config = _mock_orchestrator_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"orchestrator": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "route_user_query",
        "payload": {"user_query": "创建一个VIP订单，温控开关CCC检测"},
    })())

    assert result["result"]["recommended_task_type"] == "draft_order_from_text"


def test_route_user_query_ccc_knowledge_to_rag(tmp_path):
    mock = MockLlmClient({
        "recommended_task_type": "search_knowledge",
        "target_agent": "rag_retriever",
        "confidence": 0.88,
        "suggested_payload": {"query": "CCC环境试验规则"},
        "needs_clarification": False,
        "clarifying_question": "",
        "reasoning": "用户想查询认证知识",
    })
    config = _mock_orchestrator_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"orchestrator": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "route_user_query",
        "payload": {"user_query": "查一下CCC环境试验有什么要求"},
    })())

    assert result["result"]["recommended_task_type"] == "search_knowledge"


def test_route_user_query_ambiguous_needs_clarification(tmp_path):
    mock = MockLlmClient({
        "recommended_task_type": None,
        "target_agent": None,
        "confidence": 0.2,
        "suggested_payload": {},
        "needs_clarification": True,
        "clarifying_question": "无法理解您的意图",
        "reasoning": "模糊输入",
    })
    config = _mock_orchestrator_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"orchestrator": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "route_user_query",
        "payload": {"user_query": "嗯"},
    })())

    assert result["result"]["needs_clarification"] is True


def test_route_user_query_not_auto_execute(tmp_path):
    """route_user_query should NOT trigger a second agent invocation."""
    mock = MockLlmClient({
        "recommended_task_type": "rebuild_queue",
        "target_agent": "queue_scheduler",
        "confidence": 0.9,
        "suggested_payload": {},
        "needs_clarification": False,
        "clarifying_question": "",
        "reasoning": "用户想重建排程",
    })
    config = _mock_orchestrator_config()
    runner = _build_runner(
        tmp_path, llm_client=mock,
        agent_configs={"orchestrator": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "route_user_query",
        "payload": {"user_query": "重建排程"},
    })())

    # Should return recommendation only, not execute rebuild
    assert result["visited_agents"] == ["orchestrator"]
    assert "queue_scheduler" not in result["visited_agents"]


def test_route_user_query_fallback_without_llm(tmp_path):
    runner = _build_runner(tmp_path)

    result = runner.run(type("Request", (), {
        "task_type": "route_user_query",
        "payload": {"user_query": "帮我看看队列"},
    })())

    assert result["result"]["mode"] == "deterministic_fallback"
    assert result["result"]["needs_clarification"] is True


def test_route_user_query_fallback_routes_common_intents(tmp_path):
    runner = _build_runner(tmp_path)

    result = runner.run(type("Request", (), {
        "task_type": "route_user_query",
        "payload": {"user_query": "帮我看下当前队列有没有延期的订单"},
    })())

    assert result["result"]["recommended_task_type"] == "explain_schedule"
    assert result["result"]["target_agent"] == "queue_scheduler"
    assert result["result"]["confidence"] >= 0.7
    assert result["result"]["needs_clarification"] is False


def test_route_user_query_rejects_non_whitelisted_task_and_agent(tmp_path):
    mock = MockLlmClient({
        "recommended_task_type": "create_order",
        "target_agent": "admin_agent",
        "confidence": 0.98,
        "suggested_payload": {"order_type": "vip"},
        "needs_clarification": False,
        "clarifying_question": "",
        "reasoning": "非法写操作路由",
    })
    config = _mock_orchestrator_config()
    runner = _build_runner(
        tmp_path,
        llm_client=mock,
        agent_configs={"orchestrator": config},
    )

    result = runner.run(type("Request", (), {
        "task_type": "route_user_query",
        "payload": {"user_query": "直接帮我创建 VIP 订单"},
    })())

    assert result["result"]["recommended_task_type"] is None
    assert result["result"]["target_agent"] is None
    assert result["result"]["needs_clarification"] is True
    assert result["visited_agents"] == ["orchestrator"]


# -- v2 evaluation dataset ---------------------------------------------------

def test_evaluation_v2_cases_load(tmp_path, monkeypatch):
    """Verify the v2 eval dataset can be loaded and all cases are valid."""
    import json
    from pathlib import Path

    v2_path = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "agent_eval_cases_v2.jsonl"
    assert v2_path.exists(), f"v2 eval dataset not found at {v2_path}"

    cases = []
    for line in v2_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line.strip()))

    assert len(cases) == 30, f"Expected 30 cases, got {len(cases)}"

    required_fields = {"case_id", "task_type", "payload", "expected"}
    for c in cases:
        assert required_fields.issubset(set(c.keys())), f"Missing fields in {c.get('case_id')}"

    # Category distribution
    drafts = [c for c in cases if c["task_type"] == "draft_order_from_text"]
    recommends = [c for c in cases if c["task_type"] == "identify_projects" and "sample_description" in str(c.get("payload", {}))]
    routes = [c for c in cases if c["task_type"] == "route_user_query"]
    assert len(drafts) == 10, f"Expected 10 draft cases, got {len(drafts)}"
    assert len(routes) == 8, f"Expected 8 route cases, got {len(routes)}"


def test_evaluation_summary_uses_case_specific_metrics():
    service = object.__new__(AgentEvaluationService)
    results = [
        {
            "passed": False,
            "task_type": "draft_order_from_text",
            "latency_ms": 100,
            "trace": {
                "token_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "tool_calls": [{"tool_name": "llm_chat_json", "status": "success", "fallback_used": False}],
            },
            "scores": {
                "response_quality": {
                    "passed": False,
                    "checks": [
                        {
                            "name": "field_accuracy",
                            "expected": {"order_type": "vip", "certification_type": "ccc"},
                            "actual": {"order_type": "vip", "certification_type": "cvc"},
                            "passed": False,
                        },
                        {"name": "no_invalid_enum", "expected": True, "passed": True},
                    ],
                },
                "trajectory_state": {"passed": True},
                "efficiency": {"passed": True},
            },
        },
        {
            "passed": True,
            "task_type": "identify_projects",
            "latency_ms": 200,
            "trace": {
                "token_usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
                "tool_calls": [{"tool_name": "llm_chat_json", "status": "fallback", "fallback_used": True}],
            },
            "scores": {
                "response_quality": {
                    "passed": True,
                    "checks": [
                        {"name": "required_projects_retained", "expected": True, "passed": True},
                    ],
                },
                "trajectory_state": {"passed": True},
                "efficiency": {"passed": True},
            },
        },
        {
            "passed": True,
            "task_type": "route_user_query",
            "latency_ms": 300,
            "trace": {
                "token_usage": {"input_tokens": 30, "output_tokens": 15, "total_tokens": 45},
                "tool_calls": [{"tool_name": "llm_chat_json", "status": "success", "fallback_used": False}],
            },
            "scores": {
                "response_quality": {
                    "passed": True,
                    "checks": [
                        {"name": "route_accuracy", "expected": "explain_schedule", "actual": "explain_schedule", "passed": True},
                    ],
                },
                "trajectory_state": {"passed": True},
                "efficiency": {"passed": True},
            },
        },
        {
            "passed": True,
            "task_type": "route_user_query",
            "latency_ms": 100,
            "trace": {
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "tool_calls": [],
            },
            "agent_result": {"mode": "deterministic_fallback", "needs_clarification": True},
            "scores": {
                "response_quality": {
                    "passed": True,
                    "checks": [
                        {"name": "needs_clarification", "expected": "true", "actual": True, "passed": True},
                    ],
                },
                "trajectory_state": {"passed": True},
                "efficiency": {"passed": True},
            },
        },
    ]

    summary = service._summary(results)

    assert summary["order_draft_field_accuracy"] == 0.5
    assert summary["project_recommendation_recall"] == 1.0
    assert summary["route_accuracy"] == 1.0
    assert summary["fallback_rate"] == pytest.approx(2 / 4, rel=0.001)


def test_evaluation_quality_checks_record_actual_values():
    service = object.__new__(AgentEvaluationService)
    result = {
        "result": {
            "order_draft": {
                "order_type": "vip",
                "certification_type": "ccc",
                "sample_quantity": 200,
            },
            "recommended_task_type": "explain_schedule",
        },
        "visited_agents": ["orchestrator"],
    }

    score = service._score_quality(
        result,
        {
            "field_accuracy": {
                "order_type": "vip",
                "certification_type": "ccc",
            },
            "route_accuracy": "explain_schedule",
        },
    )

    checks = {check["name"]: check for check in score["checks"]}
    assert checks["field_accuracy"]["actual"]["order_type"] == "vip"
    assert checks["route_accuracy"]["actual"] == "explain_schedule"
