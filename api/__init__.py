from .agent import router as agent_router
from .knowledge import router as knowledge_router
from .mcp import router as mcp_router
from .monitor import router as monitor_router
from .orders import router as orders_router
from .queue import router as queue_router
from .schedules import router as schedules_router

api_routers = [
    orders_router,
    queue_router,
    schedules_router,
    monitor_router,
    knowledge_router,
    mcp_router,
    agent_router,
]
