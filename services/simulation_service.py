from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from math import ceil

from domain.schemas import CertificationType, EquipmentStatus


class SimulationService:
    """In-memory simulation of laboratory equipment and certification flows."""

    def __init__(self, equipment_catalog: dict | None = None, operations_constraints: dict | None = None) -> None:
        self.equipment = self._build_equipment_from_catalog(equipment_catalog) if equipment_catalog else self._build_default_equipment()
        self.projects = self._build_default_projects()
        self.operations_constraints = self._build_operations_constraints(operations_constraints or {})
        self.reservations: list[dict] = []

    def _build_default_equipment(self) -> list[dict]:
        definitions = [
            ("safety_tester", 2, 2, ["safety_check"], "safety_lab"),
            ("emc_tester", 1, 2, ["emc_check"], "emc_lab"),
            ("performance_bench", 1, 3, ["performance_check"], "performance_lab"),
            ("environmental_chamber", 1, 2, ["environmental_check"], "environmental_lab"),
            ("international_protocol_bench", 1, 2, ["cb_review"], "review_lab"),
        ]
        equipment: list[dict] = []
        for equipment_type, count, capacity, supported_projects, lab_area in definitions:
            for index in range(1, count + 1):
                equipment.append(
                    {
                        "id": f"{equipment_type}-{index}",
                        "equipment_type": equipment_type,
                        "name": f"{equipment_type} #{index}",
                        "capacity": capacity,
                        "supported_projects": supported_projects,
                        "lab_area": lab_area,
                        "status": EquipmentStatus.IDLE,
                    }
                )
        return equipment

    def _build_equipment_from_catalog(self, equipment_catalog: dict) -> list[dict]:
        equipment: list[dict] = []
        for definition in equipment_catalog.get("equipment_types", []):
            supported_projects = definition.get("supported_project_types") or definition.get("supported_projects") or []
            display_name = definition.get("display_name") or definition["equipment_type"]
            for index, instance in enumerate(definition.get("instances", []), start=1):
                equipment_id = instance.get("equipment_id") or instance.get("id") or f"{definition['equipment_type']}-{index}"
                equipment.append(
                    {
                        "id": equipment_id,
                        "equipment_type": instance.get("equipment_type", definition["equipment_type"]),
                        "name": instance.get("name") or f"{display_name} #{index}",
                        "capacity": int(instance.get("capacity") or instance.get("capacity_n") or definition.get("capacity_n", 1)),
                        "supported_projects": instance.get("supported_projects") or supported_projects,
                        "lab_area": instance.get("lab_area") or definition.get("lab_area", "lab"),
                        "status": EquipmentStatus(instance.get("status", EquipmentStatus.IDLE.value)),
                        "performance_factor": float(instance.get("performance_factor", definition.get("performance_factor", 1.0))),
                        "calibration_status": instance.get("calibration_status", definition.get("calibration_status", "valid")),
                        "failure_rate": float(instance.get("failure_rate", definition.get("failure_rate", 0.0))),
                    }
                )
        return equipment or self._build_default_equipment()

    def _build_default_projects(self) -> list[dict]:
        return [
            {
                "id": "ccc-safety",
                "certification_type": CertificationType.CCC.value,
                "project_type": "safety_check",
                "equipment_type": "safety_tester",
                "lab_area": "safety_lab",
                "sequence": 1,
                "duration_minutes": 30,
                "setup_minutes": 5,
                "staff_role": "safety_engineer",
                "operator_requirements": self._operator_requirements(1, ["safety_engineer"], "shared_supervision"),
                "consumable_type": "safety_probe",
                "consumable_units_per_batch": 1,
            },
            {
                "id": "ccc-emc",
                "certification_type": CertificationType.CCC.value,
                "project_type": "emc_check",
                "equipment_type": "emc_tester",
                "lab_area": "emc_lab",
                "sequence": 2,
                "duration_minutes": 45,
                "setup_minutes": 10,
                "staff_role": "emc_engineer",
                "operator_requirements": self._operator_requirements(3, ["emc_engineer", "assistant_operator"], "exclusive"),
                "consumable_type": "emc_fixture",
                "consumable_units_per_batch": 1,
            },
            {
                "id": "cvc-performance",
                "certification_type": CertificationType.CVC.value,
                "project_type": "performance_check",
                "equipment_type": "performance_bench",
                "lab_area": "performance_lab",
                "sequence": 1,
                "duration_minutes": 40,
                "setup_minutes": 5,
                "staff_role": "performance_engineer",
                "operator_requirements": self._operator_requirements(1, ["performance_engineer"], "shared_supervision"),
                "consumable_type": "load_fixture",
                "consumable_units_per_batch": 1,
            },
            {
                "id": "cvc-environment",
                "certification_type": CertificationType.CVC.value,
                "project_type": "environmental_check",
                "equipment_type": "environmental_chamber",
                "lab_area": "environmental_lab",
                "sequence": 2,
                "duration_minutes": 60,
                "setup_minutes": 15,
                "staff_role": "environmental_engineer",
                "operator_requirements": self._operator_requirements(1, ["environmental_engineer"], "setup_only"),
                "consumable_type": "environmental_tag",
                "consumable_units_per_batch": 1,
            },
            {
                "id": "international-safety",
                "certification_type": CertificationType.INTERNATIONAL.value,
                "project_type": "safety_check",
                "equipment_type": "safety_tester",
                "lab_area": "safety_lab",
                "sequence": 1,
                "duration_minutes": 30,
                "setup_minutes": 5,
                "staff_role": "safety_engineer",
                "operator_requirements": self._operator_requirements(1, ["safety_engineer"], "shared_supervision"),
                "consumable_type": "safety_probe",
                "consumable_units_per_batch": 1,
            },
            {
                "id": "international-emc",
                "certification_type": CertificationType.INTERNATIONAL.value,
                "project_type": "emc_check",
                "equipment_type": "emc_tester",
                "lab_area": "emc_lab",
                "sequence": 2,
                "duration_minutes": 45,
                "setup_minutes": 10,
                "staff_role": "emc_engineer",
                "operator_requirements": self._operator_requirements(3, ["emc_engineer", "assistant_operator"], "exclusive"),
                "consumable_type": "emc_fixture",
                "consumable_units_per_batch": 1,
            },
            {
                "id": "international-cb",
                "certification_type": CertificationType.INTERNATIONAL.value,
                "project_type": "cb_review",
                "equipment_type": "international_protocol_bench",
                "lab_area": "review_lab",
                "sequence": 3,
                "duration_minutes": 35,
                "setup_minutes": 0,
                "staff_role": "certification_reviewer",
                "operator_requirements": self._operator_requirements(1, ["certification_reviewer"], "exclusive"),
                "consumable_type": "review_sheet",
                "consumable_units_per_batch": 1,
            },
        ]

    def _operator_requirements(self, count: int, roles: list[str], mode: str) -> dict:
        return {
            "required_operator_count": count,
            "required_roles": roles,
            "supervision_mode": mode,
            "staff_phase": "running" if mode != "setup_only" else "setup",
        }

    def _build_operations_constraints(self, overrides: dict) -> dict:
        defaults = {
            "lab_areas": [
                {"lab_area": "intake", "display_name": "样品接收与前处理区"},
                {"lab_area": "safety_lab", "display_name": "安全实验室"},
                {"lab_area": "emc_lab", "display_name": "电磁兼容实验室"},
                {"lab_area": "performance_lab", "display_name": "性能实验室"},
                {"lab_area": "environmental_lab", "display_name": "环境实验室"},
                {"lab_area": "review_lab", "display_name": "国际认证评审区"},
            ],
            "shifts": [
                {"shift_id": "lab_day", "start": "09:00", "end": "18:00"},
            ],
            "employees": [
                {"employee_id": "emp-safety-1", "name": "安全工程师1", "roles": ["safety_engineer"], "skills": ["safety_check", "safety_tester"], "lab_areas": ["safety_lab"], "shift_id": "lab_day", "max_parallel_assignments": 2},
                {"employee_id": "emp-safety-2", "name": "安全工程师2", "roles": ["safety_engineer"], "skills": ["safety_check", "safety_tester"], "lab_areas": ["safety_lab"], "shift_id": "lab_day", "max_parallel_assignments": 2},
                {"employee_id": "emp-emc-1", "name": "EMC工程师1", "roles": ["emc_engineer"], "skills": ["emc_check", "emc_tester"], "lab_areas": ["emc_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
                {"employee_id": "emp-emc-2", "name": "EMC工程师2", "roles": ["emc_engineer"], "skills": ["emc_check", "emc_tester"], "lab_areas": ["emc_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
                {"employee_id": "emp-assistant-1", "name": "助理操作员1", "roles": ["assistant_operator"], "skills": ["emc_check", "performance_check"], "lab_areas": ["emc_lab", "performance_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
                {"employee_id": "emp-assistant-2", "name": "助理操作员2", "roles": ["assistant_operator"], "skills": ["emc_check", "environmental_check"], "lab_areas": ["emc_lab", "environmental_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
                {"employee_id": "emp-performance-1", "name": "性能工程师1", "roles": ["performance_engineer"], "skills": ["performance_check", "performance_bench"], "lab_areas": ["performance_lab"], "shift_id": "lab_day", "max_parallel_assignments": 2},
                {"employee_id": "emp-environment-1", "name": "环境工程师1", "roles": ["environmental_engineer"], "skills": ["environmental_check", "environmental_chamber"], "lab_areas": ["environmental_lab"], "shift_id": "lab_day", "max_parallel_assignments": 3},
                {"employee_id": "emp-review-1", "name": "认证评审员1", "roles": ["certification_reviewer"], "skills": ["cb_review"], "lab_areas": ["review_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
                {"employee_id": "emp-prep-1", "name": "样品前处理员1", "roles": ["sample_operator"], "skills": ["preprocessing"], "lab_areas": ["intake"], "shift_id": "lab_day", "max_parallel_assignments": 1},
                {"employee_id": "emp-transfer-1", "name": "转运员1", "roles": ["transfer_operator"], "skills": ["sample_transfer"], "lab_areas": ["safety_lab", "emc_lab", "performance_lab", "environmental_lab", "review_lab"], "shift_id": "lab_day", "max_parallel_assignments": 1},
            ],
            "preprocessing_resources": [{"resource_id": "prep-1", "resource_type": "prep_station"}],
            "preprocessing_rules": {
                "default": {
                    "required_minutes": 15,
                    "lab_area": "intake",
                    "required_roles": ["sample_operator"],
                    "resource_type": "prep_station",
                    "required_operator_count": 1,
                }
            },
            "transfer_resources": [{"resource_id": "cart-1", "resource_type": "transfer_cart"}],
            "transfer_matrix": {
                "intake->safety_lab": {"duration_minutes": 8, "required_roles": ["transfer_operator"], "resource_type": "transfer_cart"},
                "safety_lab->emc_lab": {"duration_minutes": 10, "required_roles": ["transfer_operator"], "resource_type": "transfer_cart"},
                "performance_lab->environmental_lab": {"duration_minutes": 12, "required_roles": ["transfer_operator"], "resource_type": "transfer_cart"},
                "environmental_lab->performance_lab": {"duration_minutes": 12, "required_roles": ["transfer_operator"], "resource_type": "transfer_cart"},
                "emc_lab->review_lab": {"duration_minutes": 10, "required_roles": ["transfer_operator"], "resource_type": "transfer_cart"},
                "environmental_lab->emc_lab": {"duration_minutes": 14, "required_roles": ["transfer_operator"], "resource_type": "transfer_cart"},
            },
            "consumables": {
                "safety_probe": {"daily_capacity": 80},
                "emc_fixture": {"daily_capacity": 45},
                "load_fixture": {"daily_capacity": 70},
                "environmental_tag": {"daily_capacity": 65},
                "review_sheet": {"daily_capacity": 60},
            },
            "maintenance_windows": [],
            "failure_events": [],
        }
        merged = deepcopy(defaults)
        for key, value in overrides.items():
            merged[key] = value
        return merged

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

    def employee_instances(self) -> list[dict]:
        return [dict(item) for item in self.operations_constraints.get("employees", [])]

    def resources_for(self, key: str, resource_type: str | None = None) -> list[dict]:
        resources = self.operations_constraints.get(key, [])
        if resource_type is None:
            return [dict(item) for item in resources]
        return [dict(item) for item in resources if item.get("resource_type") == resource_type]

    def preprocessing_profile(self, order: dict) -> dict | None:
        profile = order.get("preprocessing_profile")
        if profile:
            return dict(profile)
        return dict(self.operations_constraints.get("preprocessing_rules", {}).get("default", {}))

    def transfer_rule(self, source_lab_area: str, target_lab_area: str) -> dict | None:
        if not source_lab_area or not target_lab_area or source_lab_area == target_lab_area:
            return None
        matrix = self.operations_constraints.get("transfer_matrix", {})
        return matrix.get(f"{source_lab_area}->{target_lab_area}") or matrix.get("default")

    def consumable_capacity(self, consumable_type: str | None) -> int | None:
        if not consumable_type:
            return None
        entry = self.operations_constraints.get("consumables", {}).get(consumable_type)
        if not entry:
            return None
        return int(entry.get("daily_capacity", 0))

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
