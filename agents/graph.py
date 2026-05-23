from __future__ import annotations

from time import perf_counter
from typing import Any, Callable, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session, sessionmaker

from db.repositories import OrderRepository
from domain.schemas import AgentRunRequest, CertificationType, OrderCreate, new_id, utc_now
from rag.retriever import KnowledgeRetriever
from config.settings import AgentModelConfig
from services.notification_service import NotificationService
from services.queue_service import QueueService
from services.scheduler_service import SchedulerHeartbeatService, SchedulingCoordinatorService
from services.simulation_service import SimulationService


class ExceptionAnalysisClient(Protocol):
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
        llm_client: ExceptionAnalysisClient | None = None,
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
            },
        )
        graph.add_edge("order_manager", END)
        graph.add_edge("project_identifier", "rag_retriever")
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

    def _orchestrator(self, state: AgentState) -> AgentState:
        task_type = state.get("task_type", "")
        route_map = {
            "create_order": "order_manager",
            "list_orders": "order_manager",
            "identify_projects": "project_identifier",
            "search_knowledge": "rag_retriever",
            "query_queue": "queue_scheduler",
            "rebuild_queue": "queue_scheduler",
            "scheduler_heartbeat": "queue_scheduler",
            "analyze_schedule_options": "queue_scheduler",
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
    ) -> Literal["order_manager", "project_identifier", "rag_retriever", "queue_scheduler", "notification_agent", "exception_analyzer"]:
        return state.get("route", "exception_analyzer")  # type: ignore[return-value]

    def _order_manager(self, state: AgentState) -> AgentState:
        task_type = state.get("task_type")
        with self.session_factory() as session:
            repo = OrderRepository(session)
            if task_type == "create_order":
                order = repo.create(OrderCreate(**state.get("payload", {})))
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

    def _project_identifier(self, state: AgentState) -> AgentState:
        payload = state.get("payload", {})
        certification = CertificationType(payload.get("certification_type", CertificationType.CCC.value))
        flow = self.simulation_service.get_detection_flow(certification, payload.get("requested_projects", []))
        return {
            "result": {
                "certification_type": certification.value,
                "detection_flow": flow,
            },
            "visited_agents": self._append(state, "project_identifier"),
            "handoffs": self._handoff(
                state,
                "project_identifier",
                "rag_retriever",
                "retrieve certification context for identified projects",
            ),
        }

    def _rag_retriever(self, state: AgentState) -> AgentState:
        payload = state.get("payload", {})
        query = payload.get("query")
        if not query:
            query = f"{payload.get('certification_type', 'CCC')} 认证 检测 项目 设备 约束"
        result = dict(state.get("result", {}))
        result["knowledge_context"] = self.retriever.search(query, int(payload.get("top_k", 3)))
        return {
            "result": result,
            "visited_agents": self._append(state, "rag_retriever"),
        }

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
        else:
            with self.session_factory() as session:
                orders = OrderRepository(session).list_active()
            schedule = self.queue_service.rebuild_schedule(orders)
            result = schedule if task_type == "rebuild_queue" else self.queue_service.snapshot()
        return {
            "result": result if task_type in {"scheduler_heartbeat", "analyze_schedule_options"} else {"queue": self._json_ready(result)},
            "visited_agents": self._append(state, "queue_scheduler"),
            "handoffs": self._handoff(
                state,
                "queue_scheduler",
                "equipment_monitor",
                "request current simulated equipment status",
            ),
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
            result = {
                "notifications": self._json_ready(
                    self.notification_service.generate_from_schedule(
                        self.queue_service.snapshot(),
                        run_id=payload.get("run_id"),
                    )
                )
            }
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
            "query_notifications",
            "generate_notifications",
            "advance_simulation_clock",
            "analyze_exception",
        }:
            errors.append(f"unsupported task type: {state.get('task_type')}")
        analysis = self._deterministic_exception_analysis(snapshot)
        config = self.agent_configs.get("exception_analyzer")
        if self.llm_client and config and config.api_key:
            try:
                analysis = self.llm_client.analyze_exception(
                    config=config,
                    snapshot=self._json_ready(snapshot),
                    payload=state.get("payload", {}),
                )
            except Exception as exc:
                errors.append(f"exception_analyzer llm failed: {exc}")

        return {
            "result": analysis,
            "errors": errors,
            "visited_agents": self._append(state, "exception_analyzer"),
        }

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
                "blocked_count": snapshot["blocked_count"],
                "blocked_orders": blocked_orders,
                "bottleneck_resources": bottlenecks,
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
        if isinstance(value, list):
            return [self._json_ready(item) for item in value]
        if isinstance(value, dict):
            return {key: self._json_ready(item) for key, item in value.items()}
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def _agent_tool_calls(self, agent_name: str, state: AgentState, output: AgentState) -> list[dict[str, Any]]:
        if agent_name == "equipment_monitor":
            return [{"tool_name": "get_equipment_status", "status": "success", "adapter": "mcp_or_local"}]
        if agent_name == "rag_retriever":
            context = output.get("result", {}).get("knowledge_context", [])
            return [{"tool_name": "knowledge_search", "status": "success", "result_count": len(context)}]
        if agent_name == "queue_scheduler":
            return [{"tool_name": state.get("task_type", "queue_task"), "status": "success"}]
        if agent_name == "notification_agent":
            return [{"tool_name": state.get("task_type", "notification_task"), "status": "success"}]
        return []

    def _agent_token_usage(self, agent_name: str, output: AgentState) -> dict[str, int]:
        analysis = output.get("result", {}).get("analysis", {}) if isinstance(output.get("result"), dict) else {}
        token_usage = analysis.get("token_usage") if isinstance(analysis, dict) else None
        if isinstance(token_usage, dict):
            return {
                "input_tokens": int(token_usage.get("input_tokens", 0)),
                "output_tokens": int(token_usage.get("output_tokens", 0)),
                "total_tokens": int(token_usage.get("total_tokens", 0)),
            }
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def _aggregate_token_usage(self, trace_steps: list[dict[str, Any]]) -> dict[str, int]:
        totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for step in trace_steps:
            usage = step.get("token_usage", {})
            for key in totals:
                totals[key] += int(usage.get(key, 0) or 0)
        return totals
