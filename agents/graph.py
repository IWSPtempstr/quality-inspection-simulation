from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any, Callable, Literal, Protocol, TypedDict

from agents.llm_gateway import LlmGateway
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session, sessionmaker

from db.repositories import OrderRepository
from domain.schemas import AgentRunRequest, CertificationType, OrderCreate, new_id, utc_now
from datetime import datetime
from rag.retriever import KnowledgeRetriever
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
    validate_route_recommendation_for_pairs,
)
from config.settings import AgentModelConfig
from services.notification_service import NotificationService
from services.queue_service import QueueService
from services.scheduler_service import SchedulerHeartbeatService, SchedulingCoordinatorService
from services.simulation_service import SimulationService


class LlmClientProtocol(Protocol):
    def chat_json(
        self,
        config: AgentModelConfig,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        ...

    def analyze_exception(
        self,
        config: AgentModelConfig,
        snapshot: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


class AgentState(TypedDict, total=False):
    task_type: str
    payload: dict[str, Any]
    route: str
    result: dict[str, Any]
    visited_agents: list[str]
    handoffs: list[dict[str, Any]]
    errors: list[str]
    trace_steps: list[dict[str, Any]]


class AgentGraphRunner:
    """Hybrid multi-agent graph with one orchestrator and controlled handoffs."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        simulation_service: SimulationService,
        queue_service: QueueService,
        retriever: KnowledgeRetriever,
        tool_client: Any,
        notification_service: NotificationService | None = None,
        scheduling_coordinator: SchedulingCoordinatorService | None = None,
        scheduler_heartbeat_service: SchedulerHeartbeatService | None = None,
        agent_configs: dict[str, AgentModelConfig] | None = None,
        llm_client: LlmClientProtocol | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.simulation_service = simulation_service
        self.queue_service = queue_service
        self.retriever = retriever
        self.tool_client = tool_client
        self.notification_service = notification_service
        self.scheduling_coordinator = scheduling_coordinator
        self.scheduler_heartbeat_service = scheduler_heartbeat_service
        self.agent_configs = agent_configs or {}
        self.llm_client = llm_client
        self.llm_gateway = LlmGateway(self.agent_configs)
        self.graph = self._build_graph()

    def public_agent_configs(self) -> dict[str, dict]:
        return {
            agent_name: config.public_dict()
            for agent_name, config in self.agent_configs.items()
        }

    def run(self, request: AgentRunRequest) -> dict[str, Any]:
        trace_id = new_id("trace")
        started_at = utc_now()
        started_perf = perf_counter()
        initial_state: AgentState = {
            "task_type": request.task_type,
            "payload": request.payload,
            "visited_agents": [],
            "handoffs": [],
            "errors": [],
            "trace_steps": [],
        }
        final_state = self.graph.invoke(initial_state)
        ended_at = utc_now()
        trace_steps = final_state.get("trace_steps", [])
        tool_calls = [
            call
            for step in trace_steps
            for call in step.get("tool_calls", [])
        ]
        token_usage = self._aggregate_token_usage(trace_steps)
        errors = final_state.get("errors", [])
        trace = {
            "trace_id": trace_id,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "latency_ms": int((perf_counter() - started_perf) * 1000),
            "status": "failed" if errors else "success",
            "visited_agents": final_state.get("visited_agents", []),
            "handoffs": final_state.get("handoffs", []),
            "tool_calls": tool_calls,
            "token_usage": token_usage,
            "errors": errors,
            "steps": trace_steps,
        }
        return {
            "task_type": request.task_type,
            "payload": request.payload,
            "visited_agents": final_state.get("visited_agents", []),
            "handoffs": final_state.get("handoffs", []),
            "errors": errors,
            "trace": trace,
            "agent_configs": {
                agent_name: self.agent_configs[agent_name].public_dict()
                for agent_name in final_state.get("visited_agents", [])
                if agent_name in self.agent_configs
            },
            "result": final_state.get("result", {}),
        }

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("orchestrator", self._instrument_node("orchestrator", self._orchestrator))
        graph.add_node("order_manager", self._instrument_node("order_manager", self._order_manager))
        graph.add_node("project_identifier", self._instrument_node("project_identifier", self._project_identifier))
        graph.add_node("rag_retriever", self._instrument_node("rag_retriever", self._rag_retriever))
        graph.add_node("queue_scheduler", self._instrument_node("queue_scheduler", self._queue_scheduler))
        graph.add_node("equipment_monitor", self._instrument_node("equipment_monitor", self._equipment_monitor))
        graph.add_node("notification_agent", self._instrument_node("notification_agent", self._notification_agent))
        graph.add_node("exception_analyzer", self._instrument_node("exception_analyzer", self._exception_analyzer))

        graph.add_edge(START, "orchestrator")
        graph.add_conditional_edges(
            "orchestrator",
            self._route_from_orchestrator,
            {
                "order_manager": "order_manager",
                "project_identifier": "project_identifier",
                "rag_retriever": "rag_retriever",
                "queue_scheduler": "queue_scheduler",
                "notification_agent": "notification_agent",
                "exception_analyzer": "exception_analyzer",
                "__end__": END,
            },
        )
        graph.add_edge("order_manager", END)
        graph.add_conditional_edges(
            "project_identifier",
            self._route_from_project_identifier,
            {
                "rag_retriever": "rag_retriever",
                "__end__": END,
            },
        )
        graph.add_edge("rag_retriever", END)
        graph.add_edge("queue_scheduler", "equipment_monitor")
        graph.add_edge("equipment_monitor", END)
        graph.add_edge("notification_agent", END)
        graph.add_edge("exception_analyzer", END)
        return graph.compile()

    def _instrument_node(self, agent_name: str, handler: Callable[[AgentState], AgentState]):
        def wrapped(state: AgentState) -> AgentState:
            started_at = utc_now()
            started_perf = perf_counter()
            try:
                output = handler(state)
                step = {
                    "agent_name": agent_name,
                    "status": "success",
                    "started_at": started_at.isoformat(),
                    "ended_at": utc_now().isoformat(),
                    "latency_ms": int((perf_counter() - started_perf) * 1000),
                    "tool_calls": self._agent_tool_calls(agent_name, state, output),
                    "token_usage": self._agent_token_usage(agent_name, output),
                }
                output["trace_steps"] = [*state.get("trace_steps", []), step]
                return output
            except Exception as exc:
                ended_at = utc_now()
                step = {
                    "agent_name": agent_name,
                    "status": "failed",
                    "started_at": started_at.isoformat(),
                    "ended_at": ended_at.isoformat(),
                    "latency_ms": int((perf_counter() - started_perf) * 1000),
                    "error": str(exc),
                    "tool_calls": [],
                    "token_usage": {},
                }
                state["trace_steps"] = [*state.get("trace_steps", []), step]
                raise

        return wrapped

    def _llm_call(
        self,
        agent_name: str,
        system_prompt: str,
        user_message: str,
        fallback_result: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Unified LLM call with deterministic fallback.

        Returns ``(result_dict, llm_metadata)``.  *llm_metadata* is ``None``
        when no LLM client / config / api-key is available.
        """
        result = self.llm_gateway.chat_json(
            agent_name=agent_name,
            client=self.llm_client,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            fallback=lambda _error: fallback_result,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return result.content, (result.metadata or None)

    def _orchestrator(self, state: AgentState) -> AgentState:
        task_type = state.get("task_type", "")

        # route_user_query is handled by orchestrator itself (no dispatch)
        if task_type == "route_user_query":
            return self._handle_route_user_query(state)

        route_map = {
            "create_order": "order_manager",
            "list_orders": "order_manager",
            "identify_projects": "project_identifier",
            "search_knowledge": "rag_retriever",
            "query_queue": "queue_scheduler",
            "rebuild_queue": "queue_scheduler",
            "scheduler_heartbeat": "queue_scheduler",
            "analyze_schedule_options": "queue_scheduler",
            "explain_schedule": "queue_scheduler",
            "draft_order_from_text": "order_manager",
            "route_user_query": "orchestrator",
            "query_notifications": "notification_agent",
            "generate_notifications": "notification_agent",
            "advance_simulation_clock": "notification_agent",
            "analyze_exception": "exception_analyzer",
        }
        route = route_map.get(task_type, "exception_analyzer")
        return {
            "route": route,
            "visited_agents": self._append(state, "orchestrator"),
        }

    def _route_from_orchestrator(
        self, state: AgentState
    ) -> Any:
        return state.get("route", "exception_analyzer")  # type: ignore[return-value]

    def _route_from_project_identifier(self, state: AgentState) -> Any:
        payload = state.get("payload", {})
        if payload.get("sample_description") or payload.get("product_category"):
            return "__end__"
        return "rag_retriever"

    # ------------------------------------------------------------------
    # natural-language task routing
    # ------------------------------------------------------------------

    def _handle_route_user_query(self, state: AgentState) -> AgentState:
        """Classify a free-text user query into a recommended agent + task_type.

        Does NOT auto-execute the target task — only returns a recommendation.
        """
        user_query = state.get("payload", {}).get("user_query", "")

        target_agents = [
            {"agent": "order_manager", "task_type": "draft_order_from_text",
             "description": "自然语言创建订单草稿（不直接写入）"},
            {"agent": "order_manager", "task_type": "list_orders",
             "description": "查询订单列表"},
            {"agent": "project_identifier", "task_type": "identify_projects",
             "description": "识别检测项目和认证流程"},
            {"agent": "rag_retriever", "task_type": "search_knowledge",
             "description": "检索认证知识库和检测标准"},
            {"agent": "queue_scheduler", "task_type": "query_queue",
             "description": "查看当前队列状态"},
            {"agent": "queue_scheduler", "task_type": "explain_schedule",
             "description": "解释当前排程状态、延期原因和瓶颈"},
            {"agent": "queue_scheduler", "task_type": "rebuild_queue",
             "description": "重建排程队列（写操作，需确认）"},
            {"agent": "notification_agent", "task_type": "query_notifications",
             "description": "查询系统通知"},
            {"agent": "exception_analyzer", "task_type": "analyze_exception",
             "description": "分析异常、阻塞和瓶颈原因"},
        ]
        fallback = self._deterministic_route_user_query(user_query, target_agents)

        route_system = (
            "你是检测实验室系统的智能路由助手。"
            "根据用户自然语言输入，判断最合适的 Agent 和任务类型。"
            "输出 JSON："
            '{"recommended_task_type":"task_type字符串","target_agent":"agent名称",'
            '"confidence":0.0-1.0,"suggested_payload":{},"needs_clarification":true/false,'
            '"clarifying_question":"需要澄清的问题","reasoning":"判断依据"}'
            "如果用户意图模糊或可匹配多个任务，设置 needs_clarification=true。"
            "如果用户意图明确，设置 needs_clarification=false，confidence >= 0.7。"
        )
        route_user = json.dumps(
            {"user_query": user_query, "available_tasks": target_agents},
            ensure_ascii=False,
        )

        route_result, llm_meta = self._llm_call(
            "orchestrator", route_system, route_user, fallback,
        )

        if llm_meta and not llm_meta.get("fallback_used"):
            route_result = self._validate_route_recommendation(
                route_result,
                target_agents,
                fallback,
            )
            if route_result.get("guardrail_reason"):
                llm_meta = dict(llm_meta)
                llm_meta["fallback_used"] = True
                llm_meta["error"] = route_result["guardrail_reason"]
            else:
                route_result["mode"] = "llm"
            # Force needs_clarification when confidence is low
            if route_result.get("confidence", 0.0) < 0.7:
                route_result["needs_clarification"] = True
                if not route_result.get("clarifying_question"):
                    route_result["clarifying_question"] = (
                        "您的意图不够明确，请提供更多信息。"
                    )
            # P0-1: arbitration — when deterministic keyword match disagrees
            # with LLM, prefer deterministic for short / ambiguous queries.
            # Only applies when LLM result passed guardrail validation.
            if not route_result.get("guardrail_reason"):
                det_conf = fallback.get("confidence", 0)
                llm_conf = route_result.get("confidence", 0)
                det_task = fallback.get("recommended_task_type")
                llm_task = route_result.get("recommended_task_type")
                query_len = len(user_query.strip()) if user_query else 0
                if (
                    det_conf >= 0.82
                    and det_task
                    and det_task != llm_task
                    and (query_len <= 25 or llm_conf < 0.92)
                ):
                    route_result = fallback
                    llm_meta = dict(llm_meta or {})
                    llm_meta["arbitration"] = "deterministic_overruled_llm"

        result: dict[str, Any] = route_result
        if llm_meta:
            result["llm_metadata"] = llm_meta

        return {
            "route": "__end__",
            "result": result,
            "visited_agents": self._append(state, "orchestrator"),
        }

    def _deterministic_route_user_query(
        self,
        user_query: str,
        target_agents: list[dict[str, str]],
    ) -> dict[str, Any]:
        text = (user_query or "").strip()
        lowered = text.lower()
        fallback = {
            "recommended_task_type": None,
            "target_agent": None,
            "confidence": 0.0,
            "suggested_payload": {},
            "needs_clarification": True,
            "clarifying_question": "无法理解您的意图，请更具体地描述您的需求。",
            "candidates": target_agents,
            "mode": "deterministic_fallback",
        }
        if not text or text in {"嗯", "额", "看看", "处理一下"}:
            return fallback
        if "创建" in text and "订单" in text:
            return {
                **fallback,
                "recommended_task_type": "draft_order_from_text",
                "target_agent": "order_manager",
                "confidence": 0.82,
                "suggested_payload": {"user_text": text},
                "needs_clarification": False,
                "clarifying_question": "",
            }
        if "重建" in text or "重排" in text:
            return {
                **fallback,
                "recommended_task_type": "rebuild_queue",
                "target_agent": "queue_scheduler",
                "confidence": 0.86,
                "suggested_payload": {},
                "needs_clarification": False,
                "clarifying_question": "",
            }
        if "通知" in text or "提醒" in text:
            return {
                **fallback,
                "recommended_task_type": "query_notifications",
                "target_agent": "notification_agent",
                "confidence": 0.84,
                "suggested_payload": {},
                "needs_clarification": False,
                "clarifying_question": "",
            }
        if "异常" in text or "阻塞" in text or "瓶颈" in text:
            return {
                **fallback,
                "recommended_task_type": "analyze_exception",
                "target_agent": "exception_analyzer",
                "confidence": 0.82,
                "suggested_payload": {},
                "needs_clarification": False,
                "clarifying_question": "",
            }
        if "要求" in text or "规则" in text or "知识" in text or "认证" in text or "certification" in lowered:
            return {
                **fallback,
                "recommended_task_type": "search_knowledge",
                "target_agent": "rag_retriever",
                "confidence": 0.82,
                "suggested_payload": {"query": text},
                "needs_clarification": False,
                "clarifying_question": "",
            }
        if "延期" in text or "sla" in lowered or "排程" in text:
            return {
                **fallback,
                "recommended_task_type": "explain_schedule",
                "target_agent": "queue_scheduler",
                "confidence": 0.82,
                "suggested_payload": {},
                "needs_clarification": False,
                "clarifying_question": "",
            }
        return fallback

    def _validate_route_recommendation(
        self,
        route_result: dict[str, Any],
        target_agents: list[dict[str, str]],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        allowed_pairs = {
            (item["task_type"], item["agent"])
            for item in target_agents
        }
        if validate_route_recommendation_for_pairs(route_result, allowed_pairs):
            return route_result
        return {
            "recommended_task_type": None,
            "target_agent": None,
            "confidence": 0.0,
            "suggested_payload": {},
            "needs_clarification": True,
            "clarifying_question": "该请求无法映射到允许的只推荐任务，请补充任务目标或改用确认后的写操作入口。",
            "candidates": fallback.get("candidates", []),
            "mode": "deterministic_fallback",
            "guardrail_reason": "recommended task or target agent is not whitelisted",
        }

    def _order_manager(self, state: AgentState) -> AgentState:
        task_type = state.get("task_type")
        payload = state.get("payload", {})
        if task_type == "draft_order_from_text":
            result, llm_meta = self._draft_order_from_text(payload)
            if llm_meta:
                result["llm_metadata"] = llm_meta
            return {
                "result": result,
                "visited_agents": self._append(state, "order_manager"),
            }

        with self.session_factory() as session:
            repo = OrderRepository(session)
            if task_type == "create_order":
                order = repo.create(OrderCreate(**payload))
                if self.scheduling_coordinator:
                    self.scheduling_coordinator.event_service.create_order_event(
                        order.model_dump(mode="json"),
                        "order_created",
                    )
                result = {"order": order.model_dump(mode="json")}
            else:
                result = {"orders": [self._json_ready(order) for order in repo.list_active()]}
        return {
            "result": result,
            "visited_agents": self._append(state, "order_manager"),
        }

    # ------------------------------------------------------------------
    # natural-language order drafting
    # ------------------------------------------------------------------

    _VALID_ORDER_TYPES = {"normal", "urgent", "vip"}
    _VALID_CERT_TYPES = {"ccc", "cvc", "international"}

    def _draft_order_from_text(
        self, payload: dict
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Extract order fields from natural language — read-only, no DB write."""
        user_text = payload.get("user_text", "")
        fallback = self._deterministic_order_draft(user_text)

        draft_system = (
            "你是检测实验室的订单录入助手。从用户自然语言描述中提取订单信息。"
            "输出 JSON："
            '{"order_type":"normal|urgent|vip","sample_name":"样品名称",'
            '"sample_quantity":数量(int),"certification_type":"ccc|cvc|international",'
            '"requested_projects":["项目列表"],"promised_finish_time":"ISO格式日期或null",'
            '"field_confidence":{"order_type":0.95,...},"missing_fields":["不确定的字段"],'
            '"notes":"补充说明"}'
            "只输出合法的枚举值和数字；无法确定的字段放入 missing_fields。"
        )
        draft_user = json.dumps({"user_text": user_text}, ensure_ascii=False)

        draft, llm_meta = self._llm_call(
            "order_manager", draft_system, draft_user, fallback,
        )
        draft["_user_text"] = user_text
        if llm_meta and not llm_meta.get("fallback_used"):
            draft = self._validate_and_wrap_order_draft(draft)
            draft["mode"] = "llm"
        return draft, llm_meta

    def _deterministic_order_draft(self, user_text: str) -> dict[str, Any]:
        text = user_text or ""
        lowered = text.lower()
        draft: dict[str, Any] = {
            "order_type": None,
            "sample_name": None,
            "sample_quantity": None,
            "certification_type": None,
            "requested_projects": [],
            "promised_finish_time": None,
            "notes": "规则 fallback 仅用于草稿，仍需人工确认。",
            "field_confidence": {},
            "missing_fields": [],
        }
        if "vip" in lowered:
            draft["order_type"] = "vip"
            draft["field_confidence"]["order_type"] = 0.9
        elif "加急" in text or "紧急" in text:
            draft["order_type"] = "urgent"
            draft["field_confidence"]["order_type"] = 0.85
        elif "普通" in text:
            draft["order_type"] = "normal"
            draft["field_confidence"]["order_type"] = 0.85

        if "international" in lowered or "国际" in text:
            draft["certification_type"] = "international"
            draft["field_confidence"]["certification_type"] = 0.85
        elif "cvc" in lowered:
            draft["certification_type"] = "cvc"
            draft["field_confidence"]["certification_type"] = 0.9
        elif "ccc" in lowered:
            draft["certification_type"] = "ccc"
            draft["field_confidence"]["certification_type"] = 0.9

        quantity_match = re.search(r"(\d+)\s*(?:个|件|samples?|样品)?", text, re.IGNORECASE)
        if quantity_match:
            draft["sample_quantity"] = int(quantity_match.group(1))
            draft["field_confidence"]["sample_quantity"] = 0.85

        sample_name = self._extract_sample_name(text)
        if sample_name:
            draft["sample_name"] = sample_name
            draft["field_confidence"]["sample_name"] = 0.65

        for field in ["sample_name", "sample_quantity", "certification_type"]:
            if not draft.get(field):
                draft["missing_fields"].append(field)

        draft["_user_text"] = user_text
        wrapped = self._validate_and_wrap_order_draft(draft)
        wrapped["mode"] = "deterministic_fallback"
        return wrapped

    def _extract_sample_name(self, text: str) -> str | None:
        patterns = [
            r"为(.+?)创建",
            r"样品是(.+?)(?:，|,|。|$)",
            r"订单[：:]\s*(.+?)(?:需要|做|，|,|。|$)",
            r"(?:加急|普通|VIP|vip)\s*(?:CCC|CVC|international|国际)?[，,\s]*(.+?)(?:\d+|样品|认证|检测|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).strip(" ，,。:：")
            value = re.sub(r"(?:CCC|CVC|international|国际|认证|检测|订单|样品|数量)+", "", value, flags=re.IGNORECASE).strip()
            if value:
                return value
        return None

    def _validate_and_wrap_order_draft(self, draft: dict) -> dict:
        """Validate enumerations / types and wrap order fields into order_draft."""
        missing = list(draft.get("missing_fields", []))
        field_conf = dict(draft.get("field_confidence", {}))

        if draft.get("order_type") not in self._VALID_ORDER_TYPES:
            if "order_type" not in missing:
                missing.append("order_type")
            draft["order_type"] = None

        if draft.get("certification_type") not in self._VALID_CERT_TYPES:
            if "certification_type" not in missing:
                missing.append("certification_type")
            draft["certification_type"] = None

        promised = draft.get("promised_finish_time")
        if promised is not None and promised != "":
            try:
                if isinstance(promised, str):
                    datetime.fromisoformat(promised.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                if "promised_finish_time" not in missing:
                    missing.append("promised_finish_time")
                draft["promised_finish_time"] = None
        # P0-2: post-process LLM missing_fields to correct comprehension gaps
        _orig_text = draft.get("_user_text", "")
        # 2a: promised_finish_time — if user_text contains temporal expression
        # but LLM flagged it as missing, remove from missing_fields
        if "promised_finish_time" in missing and _orig_text:
            _time_markers = [
                "下周", "本周", "这周", "下个月", "月底", "周末",
                "明天", "后天", "今天", "周五", "周一", "之前", "前完成",
            ]
            if any(marker in _orig_text for marker in _time_markers):
                missing.remove("promised_finish_time")
                prom = draft.get("promised_finish_time")
                if prom is None or prom == "":
                    draft["promised_finish_time"] = "用户指定(需人工确认具体日期)"
        # 2b: requested_projects — not a user-missing field when
        # certification_type is known; the system derives it from the flow
        if "requested_projects" in missing and draft.get("certification_type") in self._VALID_CERT_TYPES:
            missing.remove("requested_projects")

        try:
            qty = int(draft.get("sample_quantity", 0))
            if qty <= 0:
                raise ValueError
        except (ValueError, TypeError):
            if "sample_quantity" not in missing:
                missing.append("sample_quantity")
            draft["sample_quantity"] = None

        if not draft.get("sample_name"):
            if "sample_name" not in missing:
                missing.append("sample_name")

        # Wrap validated order fields
        order_fields = {"order_type", "sample_name", "sample_quantity",
                        "certification_type", "requested_projects",
                        "promised_finish_time", "notes"}
        order_draft = {}
        for k in order_fields:
            if k in draft:
                order_draft[k] = draft.pop(k)
        order_draft["field_confidence"] = draft.pop("field_confidence", field_conf)

        return {
            "order_draft": order_draft,
            "missing_fields": missing,
            "field_confidence": field_conf,
            "confirmation_required": True,
        }

    def _project_identifier(self, state: AgentState) -> AgentState:
        payload = state.get("payload", {})
        certification = CertificationType(payload.get("certification_type", CertificationType.CCC.value))
        flow = self.simulation_service.get_detection_flow(certification, payload.get("requested_projects", []))
        result: dict[str, Any] = {
            "certification_type": certification.value,
            "detection_flow": flow,
        }

        # LLM project recommendation when sample context is provided
        if payload.get("sample_description") or payload.get("product_category"):
            recommended, llm_meta = self._recommend_projects(payload, certification.value, flow)
            result["recommended_projects"] = recommended.get("recommended_projects", [])
            result["required_projects"] = recommended.get("required_projects", [])
            result["optional_projects"] = recommended.get("optional_projects", [])
            result["risk_notes"] = recommended.get("risk_notes", [])
            result["mode"] = recommended.get("mode", "deterministic_fallback")
            if llm_meta:
                result["llm_metadata"] = llm_meta

        next_route = self._route_from_project_identifier(state)
        return {
            "result": result,
            "visited_agents": self._append(state, "project_identifier"),
            "handoffs": self._handoff(
                state,
                "project_identifier",
                "rag_retriever",
                "retrieve certification context for identified projects",
            ) if next_route == "rag_retriever" else state.get("handoffs", []),
        }

    def _recommend_projects(
        self, payload: dict, certification: str, flow: list[dict]
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """LLM-based project recommendation cross-validated against the
        deterministic detection flow."""
        required_projects = [
            {
                "project_type": p.get("project_type"),
                "equipment_type": p.get("equipment_type"),
                "reason": "认证流程必检项目",
                "is_required": True,
            }
            for p in flow
        ]
        fallback = {
            "recommended_projects": [dict(item) for item in required_projects],
            "required_projects": required_projects,
            "optional_projects": [],
            "risk_notes": [],
            "mode": "deterministic_fallback",
        }

        flow_project_types = {p.get("project_type") for p in flow}
        allowed_list = ", ".join(sorted(flow_project_types)) if flow_project_types else "(无预定义项目)"

        recommend_system = (
            "你是检测认证领域的技术专家。根据样品描述、产品类别和认证类型，"
            "推荐应进行的检测项目。输出 JSON："
            '{"recommended_projects":[{"project_type":"项目类型","equipment_type":"设备类型",'
            '"reason":"推荐原因","is_required":true/false}],'
            '"risk_notes":["需要注意的风险或建议"]}'
            f"当前认证流程支持的项目类型（只能从中选择）：{allowed_list}。"
            "只推荐以上列表中的项目类型，不虚构不存在的项目。"
        )
        sample_desc = payload.get("sample_description", "")
        product_cat = payload.get("product_category", "")
        recommend_user = json.dumps(
            {
                "sample_description": sample_desc,
                "product_category": product_cat,
                "certification_type": certification,
                "requested_projects": payload.get("requested_projects", []),
            },
            ensure_ascii=False,
        )

        rec, llm_meta = self._llm_call(
            "project_identifier", recommend_system, recommend_user, fallback,
        )

        if llm_meta and not llm_meta.get("fallback_used"):
            rec = self._validate_project_recommendations(rec, flow)
            rec["mode"] = "llm"
        return rec, llm_meta

    def _validate_project_recommendations(
        self, rec: dict, flow: list[dict]
    ) -> dict:
        """Cross-validate LLM recommendations against the deterministic flow."""
        flow_project_types = {p.get("project_type") for p in flow}
        recommended = rec.get("recommended_projects", [])
        risk_notes = list(rec.get("risk_notes", []))

        required = []
        optional = []
        seen_types = set()

        for item in recommended:
            pt = item.get("project_type", "")
            if not pt or pt in seen_types:
                continue
            seen_types.add(pt)

            if pt in flow_project_types:
                required.append(item)
            else:
                # LLM recommended something not in the deterministic flow —
                # keep as optional but flag in risk_notes
                optional.append(item)
                if not any("不在当前认证流程" in n for n in risk_notes):
                    risk_notes.append(
                        f"项目 '{pt}' 不在当前 {flow_project_types} 认证流程中，"
                        "已标记为可选，请人工确认是否需要增加。"
                    )

        # Detect projects in the flow that the LLM missed
        llm_project_types = {item.get("project_type") for item in recommended}
        for p in flow:
            pt = p.get("project_type")
            if pt and pt not in llm_project_types and pt not in seen_types:
                required.append({
                    "project_type": pt,
                    "equipment_type": p.get("equipment_type", ""),
                    "reason": "认证流程必检项目（LLM未推荐，已自动补全）",
                    "is_required": True,
                })

        rec["required_projects"] = required
        rec["optional_projects"] = optional
        rec["risk_notes"] = risk_notes
        return rec

    def _rag_retriever(self, state: AgentState) -> AgentState:
        payload = state.get("payload", {})
        query = payload.get("query")
        if not query:
            query = f"{payload.get('certification_type', 'CCC')} 认证 检测 项目 设备 约束"
        top_k = int(payload.get("top_k", 3))
        result = dict(state.get("result", {}))
        knowledge_context = self.retriever.search(query, top_k)
        result["knowledge_context"] = knowledge_context

        # LLM answer synthesis (only for search_knowledge task_type)
        if state.get("task_type") == "search_knowledge":
            answer, llm_meta = self._synthesize_knowledge_answer(query, knowledge_context)
            result["knowledge_answer"] = answer
            if llm_meta:
                result["llm_metadata"] = llm_meta

        return {
            "result": result,
            "visited_agents": self._append(state, "rag_retriever"),
        }

    def _synthesize_knowledge_answer(
        self, query: str, knowledge_context: list[dict]
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Build a natural-language answer from retrieved knowledge chunks."""
        # Deterministic fallback
        if knowledge_context and knowledge_context[0].get("source") != "fallback":
            fallback_answer = "\n\n".join(
                c["content"][:300] for c in knowledge_context
            )
            fallback_citations = [c["source"] for c in knowledge_context]
            fallback_confidence = max(
                (c.get("score", 0.0) for c in knowledge_context), default=0.0
            )
        else:
            fallback_answer = "知识库中未找到与问题直接匹配的依据，建议补充相关认证标准或设备约束文档后重新检索。"
            fallback_citations = []
            fallback_confidence = 0.0

        fallback = {
            "answer": fallback_answer,
            "citations": fallback_citations,
            "confidence": round(fallback_confidence, 4),
            "mode": "deterministic_fallback",
        }

        chunks_text = "\n---\n".join(
            f"[来源: {c['source']}] (评分: {c.get('score', 'N/A')})\n{c['content']}"
            for c in knowledge_context
        ) if knowledge_context else "（知识库中未检索到匹配片段）"

        rag_system = (
            "你是检测认证领域的知识助手。严格依据提供的知识库片段回答问题。"
            "如果知识库中没有相关信息，请明确说明\"知识库中未找到依据\"。"
            "必须在回答中引用来源（文件名）。"
        )
        rag_user = (
            f"问题：{query}\n\n知识库片段：\n{chunks_text}"
        )

        answer, llm_meta = self._llm_call(
            "rag_retriever", rag_system, rag_user, fallback,
        )
        if llm_meta and not llm_meta.get("fallback_used"):
            if not self._valid_knowledge_answer(answer, fallback_citations):
                guarded_meta = dict(llm_meta)
                guarded_meta["fallback_used"] = True
                guarded_meta["error"] = "invalid knowledge_answer schema or missing citations"
                return fallback, guarded_meta
            answer["mode"] = "llm"
        return answer, llm_meta

    def _valid_knowledge_answer(
        self,
        answer: dict[str, Any],
        fallback_citations: list[str],
    ) -> bool:
        if not valid_knowledge_answer(answer):
            return False
        if fallback_citations and not answer.get("citations"):
            return False
        return True

    def _queue_scheduler(self, state: AgentState) -> AgentState:
        task_type = state.get("task_type")
        payload = state.get("payload", {})
        if task_type == "scheduler_heartbeat" and self.scheduler_heartbeat_service:
            result = {"heartbeat": self._json_ready(self.scheduler_heartbeat_service.trigger())}
        elif task_type == "analyze_schedule_options" and self.scheduling_coordinator:
            result = self._json_ready(
                self.scheduling_coordinator.analyze_options(
                    requested_strategy=payload.get("strategy"),
                )
            )
        elif task_type == "rebuild_queue" and self.scheduling_coordinator:
            result = self._json_ready(
                self.scheduling_coordinator.rebuild(
                    trigger_source="agent",
                    requested_strategy=payload.get("strategy"),
                    extra_payload=payload,
                )
            )
        elif task_type == "explain_schedule":
            result, llm_meta = self._explain_schedule()
            if llm_meta:
                result["llm_metadata"] = llm_meta
        else:
            with self.session_factory() as session:
                orders = OrderRepository(session).list_active()
            schedule = self.queue_service.rebuild_schedule(orders)
            result = schedule if task_type == "rebuild_queue" else self.queue_service.snapshot()
        return {
            "result": result if task_type in {"scheduler_heartbeat", "analyze_schedule_options", "explain_schedule"} else {"queue": self._json_ready(result)},
            "visited_agents": self._append(state, "queue_scheduler"),
            "handoffs": self._handoff(
                state,
                "queue_scheduler",
                "equipment_monitor",
                "request current simulated equipment status",
            ),
        }

    def _explain_schedule(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Read-only schedule explanation — never triggers rebuild or writes."""
        snapshot = self.queue_service.snapshot()
        equipment = self._json_ready(self.tool_client.get_equipment_status())
        fallback = self._deterministic_schedule_explanation(snapshot, equipment)

        explain_system = (
            "你是检测队列仿真系统的排程分析 Agent。"
            "基于输入的队列快照和设备状态，用中文生成结构化分析。"
            "只基于输入数据，不虚构信息。"
            "严格按照以下 JSON 格式输出，不要包含任何解释文字："
            "{"
            '"summary":"一句话概述当前排程状态（字符串）",'
            '"sla_risks":[{"order_id":"订单ID","delay_minutes":0,"risk":"延期风险描述"}],'
            '"bottlenecks":[{"resource":"瓶颈资源名","utilization":0.0,"impact":"影响描述"}],'
            '"blocking_analysis":[{"order_id":"订单ID","reason":"阻塞原因","order_type":"订单类型","sample_name":"样品名"}],'
            '"recommended_actions":["可执行的调度建议1","建议2"]'
            "}"
        )
        explain_user = json.dumps(
            {
                "snapshot": self._json_ready(snapshot),
                "equipment_status": equipment,
            },
            ensure_ascii=False,
        )
        explanation, llm_meta = self._llm_call(
            "queue_scheduler", explain_system, explain_user, fallback,
        )
        if llm_meta and not llm_meta.get("fallback_used"):
            if not self._valid_schedule_explanation(explanation):
                guarded_meta = dict(llm_meta)
                guarded_meta["fallback_used"] = True
                guarded_meta["error"] = "invalid schedule explanation schema"
                return fallback, guarded_meta
            explanation["mode"] = "llm"
        return explanation, llm_meta

    def _valid_schedule_explanation(self, explanation: dict[str, Any]) -> bool:
        return valid_schedule_explanation(explanation)

    def _deterministic_schedule_explanation(
        self, snapshot: dict, equipment: dict
    ) -> dict[str, Any]:
        """Rule-based schedule explanation used when LLM is unavailable."""
        metrics = snapshot.get("metrics", {}) or {}
        scheduled_orders = snapshot.get("scheduled_orders", [])
        blocked_orders = snapshot.get("blocked_orders", [])
        type_dist = snapshot.get("order_type_distribution", {})

        summary_parts = [f"当前共{snapshot.get('queue_length', 0) + snapshot.get('blocked_count', 0)}个订单"]
        if type_dist:
            summary_parts.append(
                "、".join(f"{k} {v}个" for k, v in sorted(type_dist.items()))
            )
        summary_parts.append(
            f"已排程{snapshot.get('queue_length', 0)}个，阻塞{snapshot.get('blocked_count', 0)}个。"
        )
        if snapshot.get("blocked_count", 0):
            reasons = set(
                o.get("reason", "unknown") for o in blocked_orders[:10]
            )
            summary_parts.append(f"阻塞原因包括：{'；'.join(list(reasons)[:3])}。")

        sla_risks = [
            {
                "order_id": o.get("id"),
                "delay_minutes": o.get("delay_minutes", 0),
                "risk": f"{o.get('order_type', '')}订单{o.get('sample_name', '')}预计延迟{o.get('delay_minutes', 0)}分钟",
            }
            for o in scheduled_orders
            if int(o.get("delay_minutes") or 0) > 0
        ][:10]

        utilization = metrics.get("equipment_utilization", {}) if isinstance(metrics, dict) else {}
        bottlenecks = [
            {"resource": rid, "utilization": util, "impact": f"利用率 {util*100:.1f}%"}
            for rid, util in sorted(utilization.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        blocking_analysis = [
            {
                "order_id": o.get("id"),
                "reason": o.get("reason", "unknown"),
                "order_type": o.get("order_type"),
                "sample_name": o.get("sample_name"),
            }
            for o in blocked_orders[:10]
        ]

        recommended = []
        if metrics.get("personnel_blocked_count", 0):
            recommended.append("检查对应实验室区域的人员技能覆盖和并行监管上限。")
        if metrics.get("transfer_wait_minutes", 0):
            recommended.append("检查跨实验室转运资源数量和转运规则。")
        if blocked_orders:
            recommended.append("优先处理阻塞订单的设备、耗材或人员约束。")
        if metrics.get("vip_delay_minutes", 0):
            recommended.append("复核 VIP 订单承诺时间与瓶颈设备占用。")
        if not recommended:
            recommended.append("当前排程状态正常，暂无特别建议。")

        return {
            "summary": "".join(summary_parts),
            "sla_risks": sla_risks,
            "bottlenecks": bottlenecks,
            "blocking_analysis": blocking_analysis,
            "recommended_actions": recommended,
            "mode": "deterministic_fallback",
        }

    def _equipment_monitor(self, state: AgentState) -> AgentState:
        result = dict(state.get("result", {}))
        result["equipment_status"] = self._json_ready(self.tool_client.get_equipment_status())
        return {
            "result": result,
            "visited_agents": self._append(state, "equipment_monitor"),
        }

    def _notification_agent(self, state: AgentState) -> AgentState:
        payload = state.get("payload", {})
        task_type = state.get("task_type")
        result: dict[str, Any]
        if not self.notification_service:
            result = {"notifications": [], "error": "notification service unavailable"}
        elif task_type == "query_notifications":
            result = {
                "notifications": self._json_ready(
                    self.notification_service.list_notifications(
                        status=payload.get("status"),
                        notification_type=payload.get("notification_type"),
                    )
                )
            }
        elif task_type == "generate_notifications":
            notifications = self.notification_service.generate_from_schedule(
                self.queue_service.snapshot(),
                run_id=payload.get("run_id"),
            )
            enhanced, llm_meta = self._enhance_notifications(notifications)
            result = {"notifications": self._json_ready(enhanced)}
            if llm_meta:
                result["llm_metadata"] = llm_meta
        elif task_type == "advance_simulation_clock":
            result = {
                "clock": self._json_ready(
                    self.notification_service.advance_clock(
                        current_time=payload.get("current_time"),
                        delta_minutes=payload.get("delta_minutes"),
                    )
                )
            }
        else:
            result = {"notifications": [], "error": f"unsupported notification task: {task_type}"}
        return {
            "result": result,
            "visited_agents": self._append(state, "notification_agent"),
        }

    def _enhance_notifications(
        self, notifications: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Enhance notification titles/messages with LLM while preserving
        rule-generated type, severity, status, and trigger times."""
        config = self.agent_configs.get("notification_agent")
        if not self.llm_client or not config or not config.api_key:
            return notifications, None

        notify_system = (
            "你是检测实验室的通知优化 Agent。"
            "基于原始通知信息，优化标题和正文使其更清晰、更具操作性，"
            "并给出 1-3 条具体操作建议。"
            "保持专业、简洁的风格。"
            "输出 JSON：{\"title\": \"...\", \"message\": \"...\", \"suggested_actions\": [\"...\"]}"
        )

        enhanced: list[dict[str, Any]] = []
        any_llm_used = False
        last_model = ""
        total_input = 0
        total_output = 0
        total_all = 0

        for n in notifications:
            try:
                llm_result = self.llm_gateway.raw_chat_json(
                    agent_name="notification_agent",
                    client=self.llm_client,
                    messages=[
                        {"role": "system", "content": notify_system},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "notification_type": str(n.get("notification_type", "")),
                                    "severity": n.get("severity", "info"),
                                    "current_title": n.get("title", ""),
                                    "current_message": n.get("message", ""),
                                    "order_id": n.get("order_id"),
                                    "context": n.get("payload", {}),
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                )
                content = llm_result.get("content", {})
                n["title"] = content.get("title", n["title"])
                n["message"] = content.get("message", n["message"])
                n["suggested_actions"] = content.get("suggested_actions", [])
                n["llm_enhanced"] = True
                any_llm_used = True
                last_model = llm_result.get("model", "")
                tu = llm_result.get("token_usage", {})
                total_input += int(tu.get("input_tokens", 0))
                total_output += int(tu.get("output_tokens", 0))
                total_all += int(tu.get("total_tokens", 0))
            except Exception:
                n["llm_enhanced"] = False
            enhanced.append(n)

        if any_llm_used:
            return enhanced, {
                "llm_called": True,
                "model": last_model,
                "token_usage": {
                    "input_tokens": total_input,
                    "output_tokens": total_output,
                    "total_tokens": total_all,
                },
                "fallback_used": False,
            }
        return enhanced, None

    def _exception_analyzer(self, state: AgentState) -> AgentState:
        snapshot = self.queue_service.snapshot()
        errors = list(state.get("errors", []))
        if state.get("task_type") not in {
            "create_order",
            "list_orders",
            "identify_projects",
            "search_knowledge",
            "query_queue",
            "rebuild_queue",
            "scheduler_heartbeat",
            "analyze_schedule_options",
            "explain_schedule",
            "query_notifications",
            "generate_notifications",
            "advance_simulation_clock",
            "analyze_exception",
            "draft_order_from_text",
            "route_user_query",
        }:
            errors.append(f"unsupported task type: {state.get('task_type')}")

        fallback = self._deterministic_exception_analysis(snapshot)

        exception_system = (
            "你是检测队列仿真系统的异常分析 Agent。"
            "分析以下队列快照，输出结构化JSON，包含："
            "root_causes（根因数组，每项含cause和evidence）、"
            "affected_orders（受影响订单，每项含order_id和impact）、"
            "bottleneck_resources（瓶颈资源数组）、"
            "risk_level（critical/high/medium/low）、"
            "recommended_actions（建议操作数组）。"
            "只基于输入数据解释阻塞、延期和瓶颈，不虚构数据。"
        )
        exception_user = json.dumps(
            {
                "snapshot": self._json_ready(snapshot),
                "payload": state.get("payload", {}),
            },
            ensure_ascii=False,
        )

        analysis, llm_meta = self._llm_call(
            "exception_analyzer", exception_system, exception_user, fallback,
        )
        if llm_meta and not llm_meta.get("fallback_used"):
            if self._valid_exception_analysis(analysis):
                analysis["mode"] = "llm"
                analysis["model"] = llm_meta["model"]
                result = {
                    "blocked_orders": fallback["blocked_orders"],
                    "blocked_count": fallback["blocked_count"],
                    "analysis": analysis,
                    "llm_metadata": llm_meta,
                }
            else:
                guarded_meta = dict(llm_meta)
                guarded_meta["fallback_used"] = True
                guarded_meta["error"] = "invalid exception analysis schema"
                result = fallback
                result["llm_metadata"] = guarded_meta
        elif llm_meta and llm_meta.get("fallback_used"):
            # LLM was called but failed — use fallback with error
            result = fallback
            errors.append(
                f"exception_analyzer llm failed: {llm_meta.get('error', 'unknown')}"
            )
            result["llm_metadata"] = llm_meta
        else:
            result = fallback

        return {
            "result": result,
            "errors": errors,
            "visited_agents": self._append(state, "exception_analyzer"),
        }

    def _valid_exception_analysis(self, analysis: dict[str, Any]) -> bool:
        return valid_exception_analysis(analysis)

    def _deterministic_exception_analysis(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        blocked_orders = self._json_ready(snapshot["blocked_orders"])
        metrics = self._json_ready(snapshot.get("metrics", {}))
        utilization = metrics.get("equipment_utilization", {}) if isinstance(metrics, dict) else {}
        bottlenecks = [
            {"resource_id": resource_id, "utilization": value}
            for resource_id, value in sorted(utilization.items(), key=lambda item: item[1], reverse=True)[:5]
        ]
        blocked_distribution = metrics.get("blocked_reason_distribution", {}) if isinstance(metrics, dict) else {}
        delayed_orders = [
            {
                "order_id": order.get("id"),
                "order_type": order.get("order_type"),
                "sample_name": order.get("sample_name"),
                "delay_minutes": order.get("delay_minutes", 0),
            }
            for order in snapshot.get("scheduled_orders", [])
            if int(order.get("delay_minutes") or 0) > 0
        ][:10]
        recommended_actions = []
        if metrics.get("personnel_blocked_count", 0):
            recommended_actions.append("检查对应实验室区域的人员技能覆盖和并行监管上限。")
        if metrics.get("transfer_wait_minutes", 0):
            recommended_actions.append("检查跨实验室转运资源数量和转运规则。")
        if blocked_orders:
            recommended_actions.append("优先处理阻塞订单的设备、耗材或人员约束。")
        if metrics.get("vip_delay_minutes", 0):
            recommended_actions.append("复核 VIP 订单承诺时间与瓶颈设备占用。")
        return {
            "blocked_orders": blocked_orders,
            "blocked_count": snapshot["blocked_count"],
            "analysis": {
                "mode": "deterministic_fallback",
                "root_causes": [],
                "affected_orders": delayed_orders,
                "bottleneck_resources": bottlenecks,
                "risk_level": "high" if snapshot["blocked_count"] > 5 else ("medium" if snapshot["blocked_count"] > 0 else "low"),
                "sla_risks": {
                    "on_time_rate": metrics.get("on_time_rate"),
                    "vip_delay_minutes": metrics.get("vip_delay_minutes", 0),
                    "urgent_delay_minutes": metrics.get("urgent_delay_minutes", 0),
                    "normal_delay_minutes": metrics.get("normal_delay_minutes", 0),
                    "top_delayed_orders": delayed_orders,
                },
                "blocking": {
                    "blocked_reason_distribution": blocked_distribution,
                    "personnel_blocked_count": metrics.get("personnel_blocked_count", 0),
                },
                "recommended_actions": recommended_actions,
            },
        }

    def _append(self, state: AgentState, agent_name: str) -> list[str]:
        return [*state.get("visited_agents", []), agent_name]

    def _handoff(self, state: AgentState, source: str, target: str, reason: str) -> list[dict[str, Any]]:
        return [*state.get("handoffs", []), {"from": source, "to": target, "reason": reason}]

    def _json_ready(self, value: Any) -> Any:
        return json_ready(value)

    def _agent_tool_calls(self, agent_name: str, state: AgentState, output: AgentState) -> list[dict[str, Any]]:
        return agent_tool_calls({
            "agent_name": agent_name,
            "task_type": state.get("task_type"),
            "result": output.get("result", {}),
        })

    def _agent_token_usage(self, agent_name: str, output: AgentState) -> dict[str, int]:
        return agent_token_usage({"agent_name": agent_name, "result": output.get("result", {})})

    def _aggregate_token_usage(self, trace_steps: list[dict[str, Any]]) -> dict[str, int]:
        return aggregate_token_usage(trace_steps)
