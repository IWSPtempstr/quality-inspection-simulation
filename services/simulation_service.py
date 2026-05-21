from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import ceil

from domain.schemas import CertificationType, EquipmentStatus


class SimulationService:
    """In-memory simulation of laboratory equipment and certification flows."""

    def __init__(self, operations_constraints: dict | None = None) -> None:
        self.equipment = self._build_default_equipment()
        self.projects = self._build_default_projects()
        self.operations_constraints = operations_constraints or {}
        self.reservations: list[dict] = []

    def _build_default_equipment(self) -> list[dict]:
        definitions = [
            ("safety_tester", 2, 2, ["safety_check"]),
            ("emc_tester", 1, 2, ["emc_check"]),
            ("performance_bench", 1, 3, ["performance_check"]),
            ("environmental_chamber", 1, 2, ["environmental_check"]),
            ("international_protocol_bench", 1, 2, ["cb_review"]),
        ]
        equipment: list[dict] = []
        for equipment_type, count, capacity, supported_projects in definitions:
            for index in range(1, count + 1):
                equipment.append(
                    {
                        "id": f"{equipment_type}-{index}",
                        "equipment_type": equipment_type,
                        "name": f"{equipment_type} #{index}",
                        "capacity": capacity,
                        "supported_projects": supported_projects,
                        "status": EquipmentStatus.IDLE,
                    }
                )
        return equipment

    def _build_default_projects(self) -> list[dict]:
        return [
            {
                "id": "ccc-safety",
                "certification_type": CertificationType.CCC.value,
                "project_type": "safety_check",
                "equipment_type": "safety_tester",
                "sequence": 1,
                "duration_minutes": 30,
            },
            {
                "id": "ccc-emc",
                "certification_type": CertificationType.CCC.value,
                "project_type": "emc_check",
                "equipment_type": "emc_tester",
                "sequence": 2,
                "duration_minutes": 45,
            },
            {
                "id": "cvc-performance",
                "certification_type": CertificationType.CVC.value,
                "project_type": "performance_check",
                "equipment_type": "performance_bench",
                "sequence": 1,
                "duration_minutes": 40,
            },
            {
                "id": "cvc-environment",
                "certification_type": CertificationType.CVC.value,
                "project_type": "environmental_check",
                "equipment_type": "environmental_chamber",
                "sequence": 2,
                "duration_minutes": 60,
            },
            {
                "id": "international-safety",
                "certification_type": CertificationType.INTERNATIONAL.value,
                "project_type": "safety_check",
                "equipment_type": "safety_tester",
                "sequence": 1,
                "duration_minutes": 30,
            },
            {
                "id": "international-emc",
                "certification_type": CertificationType.INTERNATIONAL.value,
                "project_type": "emc_check",
                "equipment_type": "emc_tester",
                "sequence": 2,
                "duration_minutes": 45,
            },
            {
                "id": "international-cb",
                "certification_type": CertificationType.INTERNATIONAL.value,
                "project_type": "cb_review",
                "equipment_type": "international_protocol_bench",
                "sequence": 3,
                "duration_minutes": 35,
            },
        ]

    def reset_runtime_state(self) -> None:
        self.reservations.clear()
        for item in self.equipment:
            if item["status"] != EquipmentStatus.OFFLINE:
                item["status"] = EquipmentStatus.IDLE

    def seed_equipment(self) -> list[dict]:
        return [
            {
                **item,
                "status": item["status"].value if isinstance(item["status"], EquipmentStatus) else item["status"],
            }
            for item in self.equipment
        ]

    def seed_projects(self) -> list[dict]:
        return [dict(item) for item in self.projects]

    def set_equipment_offline(self, equipment_type: str) -> None:
        for item in self.equipment:
            if item["equipment_type"] == equipment_type:
                item["status"] = EquipmentStatus.OFFLINE

    def list_equipment(self) -> list[dict]:
        return [dict(item) for item in self.equipment]

    def equipment_instances_for(self, equipment_type: str) -> list[dict]:
        return [
            item
            for item in self.equipment
            if item["equipment_type"] == equipment_type and item["status"] != EquipmentStatus.OFFLINE
        ]

    def maintenance_windows_for(self, equipment_id: str) -> list[dict]:
        events = [
            *self.operations_constraints.get("maintenance_windows", []),
            *self.operations_constraints.get("failure_events", []),
        ]
        windows = [
            {
                **event,
                "start_dt": self._parse_datetime(event["start"]),
                "end_dt": self._parse_datetime(event["end"]),
            }
            for event in events
            if event.get("equipment_id") == equipment_id
        ]
        return sorted(windows, key=lambda item: item["start_dt"])

    def get_detection_flow(
        self,
        certification_type: CertificationType | str,
        requested_projects: list[str] | None = None,
    ) -> list[dict]:
        cert_value = certification_type.value if isinstance(certification_type, CertificationType) else certification_type
        requested = set(requested_projects or [])
        flow = [
            dict(project)
            for project in self.projects
            if project["certification_type"] == cert_value
            and (not requested or project["id"] in requested or project["project_type"] in requested)
        ]
        return sorted(flow, key=lambda item: item["sequence"])

    def available_equipment_for(self, equipment_type: str) -> list[dict]:
        return [
            item
            for item in self.equipment
            if item["equipment_type"] == equipment_type and item["status"] != EquipmentStatus.OFFLINE
        ]

    def equipment_capacity(self, equipment_type: str) -> int:
        equipment = self.available_equipment_for(equipment_type)
        if not equipment:
            return 0
        return max(item["capacity"] for item in equipment)

    def equipment_instance_capacity(self, equipment_id: str) -> int:
        for item in self.equipment:
            if item["id"] == equipment_id:
                return int(item["capacity"])
        return 0

    def required_batches(self, equipment_type: str, sample_quantity: int) -> int:
        capacity = self.equipment_capacity(equipment_type)
        if capacity <= 0:
            return 0
        return ceil(sample_quantity / capacity)

    def reserve_equipment_slot(
        self,
        equipment_type: str,
        order_id: str,
        start_minute: int,
        duration_minutes: int,
        sample_quantity: int,
    ) -> dict:
        capacity = self.equipment_capacity(equipment_type)
        if capacity <= 0:
            return {
                "reserved": False,
                "equipment_type": equipment_type,
                "reason": f"no available equipment for {equipment_type}",
            }
        reservation = {
            "reserved": True,
            "order_id": order_id,
            "equipment_type": equipment_type,
            "start_minute": start_minute,
            "duration_minutes": duration_minutes,
            "end_minute": start_minute + duration_minutes,
            "sample_quantity": sample_quantity,
            "batch_count": min(capacity, sample_quantity),
            "required_batches": ceil(sample_quantity / capacity),
        }
        self.reservations.append(reservation)
        return reservation

    def equipment_status_summary(self) -> dict:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for item in self.equipment:
            grouped[item["equipment_type"]].append(item)
        return {
            equipment_type: {
                "total": len(items),
                "idle": sum(1 for item in items if item["status"] == EquipmentStatus.IDLE),
                "offline": sum(1 for item in items if item["status"] == EquipmentStatus.OFFLINE),
                "capacity": max(item["capacity"] for item in items),
            }
            for equipment_type, items in grouped.items()
        }

    def _parse_datetime(self, value: datetime | str) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)
