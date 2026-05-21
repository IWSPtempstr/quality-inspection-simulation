from __future__ import annotations

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - import guard for partial environments
    FastMCP = None

from services.queue_service import QueueService
from services.simulation_service import SimulationService
from services.tool_client import LocalSimulationToolClient


def create_mcp_server():
    if FastMCP is None:
        raise RuntimeError("mcp package is not available in this environment")

    simulation = SimulationService()
    queue_service = QueueService(simulation)
    client = LocalSimulationToolClient(simulation, queue_service)
    server = FastMCP("quality-inspection-simulation")

    @server.tool()
    def get_equipment_status() -> dict:
        return client.get_equipment_status()

    @server.tool()
    def get_queue_snapshot() -> dict:
        return client.get_queue_snapshot()

    @server.tool()
    def reserve_equipment_slot(
        equipment_type: str,
        order_id: str,
        start_minute: int,
        duration_minutes: int,
        sample_quantity: int,
    ) -> dict:
        return client.reserve_equipment_slot(
            equipment_type=equipment_type,
            order_id=order_id,
            start_minute=start_minute,
            duration_minutes=duration_minutes,
            sample_quantity=sample_quantity,
        )

    return server


if __name__ == "__main__":
    create_mcp_server().run()
