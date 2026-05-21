from __future__ import annotations

from services.queue_service import QueueService
from services.simulation_service import SimulationService


class LocalSimulationToolClient:
    """Local MCP-compatible facade used by agents and tests."""

    def __init__(self, simulation_service: SimulationService, queue_service: QueueService) -> None:
        self.simulation_service = simulation_service
        self.queue_service = queue_service

    def get_equipment_status(self) -> dict:
        return {
            "equipment": self.simulation_service.list_equipment(),
            "summary": self.simulation_service.equipment_status_summary(),
        }

    def get_queue_snapshot(self) -> dict:
        return self.queue_service.snapshot()

    def reserve_equipment_slot(
        self,
        equipment_type: str,
        order_id: str,
        start_minute: int,
        duration_minutes: int,
        sample_quantity: int,
    ) -> dict:
        return self.simulation_service.reserve_equipment_slot(
            equipment_type=equipment_type,
            order_id=order_id,
            start_minute=start_minute,
            duration_minutes=duration_minutes,
            sample_quantity=sample_quantity,
        )
