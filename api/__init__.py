from .admin import router as admin_router
from .agent import router as agent_router
from .knowledge import router as knowledge_router
from .mcp import router as mcp_router
from .monitor import router as monitor_router
from .notifications import router as notifications_router
from .orders import router as orders_router
from .queue import router as queue_router
from .schedules import router as schedules_router
from .scheduling import router as scheduling_router
from .simulation import router as simulation_router

api_routers = [
    admin_router,
    orders_router,
    queue_router,
    schedules_router,
    monitor_router,
    knowledge_router,
    mcp_router,
    notifications_router,
    simulation_router,
    scheduling_router,
    agent_router,
]
