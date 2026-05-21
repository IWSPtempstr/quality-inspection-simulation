from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents import AgentGraphRunner
from api import api_routers
from config.settings import get_settings
from db.repositories import DetectionProjectRepository, EquipmentRepository
from db.session import create_tables, get_session_factory
from rag.retriever import KnowledgeRetriever
from services.queue_service import QueueService
from services.simulation_service import SimulationService
from services.tool_client import LocalSimulationToolClient


def _seed_reference_data(app: FastAPI) -> None:
    with app.state.session_factory() as session:
        EquipmentRepository(session).seed_if_empty(app.state.simulation_service.seed_equipment())
        DetectionProjectRepository(session).seed_if_empty(app.state.simulation_service.seed_projects())


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

    simulation_service = SimulationService()
    queue_service = QueueService(simulation_service)
    knowledge_retriever = KnowledgeRetriever(settings.knowledge_base_dir)
    tool_client = LocalSimulationToolClient(simulation_service, queue_service)

    app.state.session_factory = session_factory
    app.state.simulation_service = simulation_service
    app.state.queue_service = queue_service
    app.state.knowledge_retriever = knowledge_retriever
    app.state.tool_client = tool_client
    app.state.agent_graph = AgentGraphRunner(
        session_factory=session_factory,
        simulation_service=simulation_service,
        queue_service=queue_service,
        retriever=knowledge_retriever,
        tool_client=tool_client,
    )

    _seed_reference_data(app)

    for router in api_routers:
        app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8002)
