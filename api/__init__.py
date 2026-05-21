from .agent import router as agent_router
from .knowledge import router as knowledge_router
from .monitor import router as monitor_router
from .orders import router as orders_router
from .queue import router as queue_router

api_routers = [
    orders_router,
    queue_router,
    monitor_router,
    knowledge_router,
    agent_router,
]

