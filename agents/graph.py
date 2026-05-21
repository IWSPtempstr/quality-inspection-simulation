from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session, sessionmaker

from db.repositories import OrderRepository
from domain.schemas import AgentRunRequest, CertificationType, OrderCreate
from rag.retriever import KnowledgeRetriever
from config.settings import AgentModelConfig
from services.queue_service import QueueService
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


class AgentGraphRunner:
    """Hybrid multi-agent graph with one orchestrator and controlled handoffs."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        simulation_service: SimulationService,
        queue_service: QueueService,
        retriever: KnowledgeRetriever,
        tool_client: Any,
        agent_configs: dict[str, AgentModelConfig] | None = None,
        llm_client: ExceptionAnalysisClient | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.simulation_service = simulation_service
        self.queue_service = queue_service
        self.retriever = retriever
        self.tool_client = tool_client
        self.agent_configs = agent_configs or {}
        self.llm_client = llm_client
        self.graph = self._build_graph()

    def public_agent_configs(self) -> dict[str, dict]:
        return {
            agent_name: config.public_dict()
            for agent_name, config in self.agent_configs.items()
        }

    def run(self, request: AgentRunRequest) -> dict[str, Any]:
        initial_state: AgentState = {
            "task_type": request.task_type,
            "payload": request.payload,
            "visited_agents": [],
            "handoffs": [],
            "errors": [],
        }
        final_state = self.graph.invoke(initial_state)
        return {
            "task_type": request.task_type,
            "payload": request.payload,
            "visited_agents": final_state.get("visited_agents", []),
            "handoffs": final_state.get("handoffs", []),
            "errors": final_state.get("errors", []),
            "agent_configs": {
                agent_name: self.agent_configs[agent_name].public_dict()
                for agent_name in final_state.get("visited_agents", [])
                if agent_name in self.agent_configs
            },
            "result": final_state.get("result", {}),
        }

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("orchestrator", self._orchestrator)
        graph.add_node("order_manager", self._order_manager)
        graph.add_node("project_identifier", self._project_identifier)
        graph.add_node("rag_retriever", self._rag_retriever)
        graph.add_node("queue_scheduler", self._queue_scheduler)
        graph.add_node("equipment_monitor", self._equipment_monitor)
        graph.add_node("exception_analyzer", self._exception_analyzer)

        graph.add_edge(START, "orchestrator")
        graph.add_conditional_edges(
            "orchestrator",
            self._route_from_orchestrator,
            {
                "order_manager": "order_manager",
                "project_identifier": "project_identifier",
                "rag_retriever": "rag_retriever",
                "queue_scheduler": "queue_scheduler",
                "exception_analyzer": "exception_analyzer",
            },
        )
        graph.add_edge("order_manager", END)
        graph.add_edge("project_identifier", "rag_retriever")
        graph.add_edge("rag_retriever", END)
        graph.add_edge("queue_scheduler", "equipment_monitor")
        graph.add_edge("equipment_monitor", END)
        graph.add_edge("exception_analyzer", END)
        return graph.compile()

    def _orchestrator(self, state: AgentState) -> AgentState:
        task_type = state.get("task_type", "")
        route_map = {
            "create_order": "order_manager",
            "list_orders": "order_manager",
            "identify_projects": "project_identifier",
            "search_knowledge": "rag_retriever",
            "query_queue": "queue_scheduler",
            "rebuild_queue": "queue_scheduler",
            "analyze_exception": "exception_analyzer",
        }
        route = route_map.get(task_type, "exception_analyzer")
        return {
            "route": route,
            "visited_agents": self._append(state, "orchestrator"),
        }

    def _route_from_orchestrator(
        self, state: AgentState
    ) -> Literal["order_manager", "project_identifier", "rag_retriever", "queue_scheduler", "exception_analyzer"]:
        return state.get("route", "exception_analyzer")  # type: ignore[return-value]

    def _order_manager(self, state: AgentState) -> AgentState:
        task_type = state.get("task_type")
        with self.session_factory() as session:
            repo = OrderRepository(session)
            if task_type == "create_order":
                order = repo.create(OrderCreate(**state.get("payload", {})))
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
        with self.session_factory() as session:
            orders = OrderRepository(session).list_active()
        schedule = self.queue_service.rebuild_schedule(orders)
        task_type = state.get("task_type")
        result = schedule if task_type == "rebuild_queue" else self.queue_service.snapshot()
        return {
            "result": {"queue": self._json_ready(result)},
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
        return {
            "blocked_orders": blocked_orders,
            "blocked_count": snapshot["blocked_count"],
            "analysis": {
                "mode": "deterministic_fallback",
                "blocked_count": snapshot["blocked_count"],
                "blocked_orders": blocked_orders,
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
