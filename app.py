from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agents import AgentGraphRunner
from api import core_api_routers, demo_api_routers
from config.settings import get_settings
from db.repositories import DetectionProjectRepository, EquipmentRepository, UserRepository
from db.session import create_tables, get_session_factory
from rag.retriever import KnowledgeRetriever
from services.queue_service import QueueService
from services.simulation_service import SimulationService
from services.mcp_client import McpToolClient
from services.llm_client import OpenAICompatibleLlmClient
from services.notification_service import NotificationService
from services.monitoring_service import MonitoringReportService
from services.dataset_replay_service import DatasetReplayService
from services.evaluation_service import AgentEvaluationService
from services.scheduler_service import (
    ScheduleOptimizerService,
    SchedulerHeartbeatService,
    SchedulingCoordinatorService,
    SchedulingEventService,
)
from services.security_service import AuditService, PermissionService
from services.tool_client import LocalSimulationToolClient
from web import router as web_router


class LazyApp:
    def __init__(self) -> None:
        self._app: FastAPI | None = None

    async def __call__(self, scope, receive, send) -> None:
        if self._app is None:
            self._app = create_app()
        await self._app(scope, receive, send)


def _seed_reference_data(app: FastAPI) -> None:
    with app.state.session_factory() as session:
        EquipmentRepository(session).seed_if_empty(app.state.simulation_service.seed_equipment())
        DetectionProjectRepository(session).seed_if_empty(app.state.simulation_service.seed_projects())
        UserRepository(session).seed_if_empty()


def _load_operations_constraints(path) -> dict:
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _load_equipment_catalog(path) -> dict | None:
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="面向电器产品质量检测队列的多Agent协同仿真系统",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    session_factory = get_session_factory(settings.database_url)
    create_tables(session_factory)

    simulation_service = SimulationService(
        equipment_catalog=_load_equipment_catalog(settings.equipment_catalog_path),
        operations_constraints=_load_operations_constraints(settings.operations_constraints_path)
    )
    queue_service = QueueService(simulation_service)
    notification_service = NotificationService(session_factory)
    scheduling_event_service = SchedulingEventService(
        session_factory=session_factory,
        debounce_seconds=settings.scheduler_debounce_seconds,
        immediate_severities=settings.scheduler_immediate_severities,
    )
    schedule_optimizer = ScheduleOptimizerService(
        queue_service=queue_service,
        default_strategy=settings.scheduler_default_strategy,
    )
    scheduling_coordinator = SchedulingCoordinatorService(
        session_factory=session_factory,
        queue_service=queue_service,
        notification_service=notification_service,
        event_service=scheduling_event_service,
        optimizer=schedule_optimizer,
    )
    scheduler_heartbeat_service = SchedulerHeartbeatService(
        scheduling_coordinator,
        enabled=settings.scheduler_heartbeat_enabled,
        interval_seconds=settings.scheduler_heartbeat_interval_seconds,
    )
    permission_service = PermissionService()
    audit_service = AuditService(session_factory)
    monitoring_report_service = MonitoringReportService(session_factory, settings.base_dir)
    dataset_replay_service = None
    if settings.enable_dataset_replay:
        dataset_replay_service = DatasetReplayService(
            session_factory=session_factory,
            base_dir=settings.base_dir,
            scheduling_event_service=scheduling_event_service,
            scheduler_heartbeat_service=scheduler_heartbeat_service,
            notification_service=notification_service,
        )
    knowledge_retriever = KnowledgeRetriever(settings.knowledge_base_dir, index_dir=settings.rag_index_dir)
    fallback_tool_client = LocalSimulationToolClient(simulation_service, queue_service)
    tool_client = fallback_tool_client
    if settings.enable_mcp_simulation:
        tool_client = McpToolClient(
            command=settings.mcp_server_command,
            args=settings.mcp_server_args or [],
            fallback_client=fallback_tool_client,
            adapter_type=settings.mcp_adapter_type,
            cwd=settings.mcp_server_cwd,
        )

    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.simulation_service = simulation_service
    app.state.queue_service = queue_service
    app.state.notification_service = notification_service
    app.state.scheduling_event_service = scheduling_event_service
    app.state.schedule_optimizer = schedule_optimizer
    app.state.scheduling_coordinator = scheduling_coordinator
    app.state.scheduler_heartbeat_service = scheduler_heartbeat_service
    app.state.permission_service = permission_service
    app.state.audit_service = audit_service
    app.state.monitoring_report_service = monitoring_report_service
    if dataset_replay_service is not None:
        app.state.dataset_replay_service = dataset_replay_service
    app.state.knowledge_retriever = knowledge_retriever
    app.state.tool_client = tool_client
    agent_graph = AgentGraphRunner(
        session_factory=session_factory,
        simulation_service=simulation_service,
        queue_service=queue_service,
        retriever=knowledge_retriever,
        tool_client=tool_client,
        notification_service=notification_service,
        scheduling_coordinator=scheduling_coordinator,
        scheduler_heartbeat_service=scheduler_heartbeat_service,
        agent_configs=settings.agent_configs,
        llm_client=OpenAICompatibleLlmClient(),
    )
    app.state.agent_graph = agent_graph
    app.state.agent_evaluation_service = AgentEvaluationService(
        session_factory=session_factory,
        base_dir=settings.base_dir,
        agent_graph=agent_graph,
    )

    _seed_reference_data(app)

    if settings.scheduler_heartbeat_enabled:
        app.router.add_event_handler("startup", scheduler_heartbeat_service.start_background_loop)
        app.router.add_event_handler("shutdown", scheduler_heartbeat_service.stop_background_loop)

    for router in core_api_routers:
        app.include_router(router)
    if settings.enable_dataset_replay:
        app.include_router(demo_api_routers["datasets"])
    if settings.enable_simulation_clock:
        app.include_router(demo_api_routers["simulation"])
    if settings.enable_mcp_simulation:
        app.include_router(demo_api_routers["mcp"])
    if settings.enable_web_ui:
        app.include_router(web_router)
        app.mount("/static", StaticFiles(directory="web/static"), name="static")
    return app


app = LazyApp()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8002)
