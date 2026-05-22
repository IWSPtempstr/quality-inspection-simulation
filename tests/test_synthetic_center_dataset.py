from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_synthetic_center_dataset import LARGE_CONFIG, generate_dataset
from scripts.validate_synthetic_center_dataset import validate_dataset


def test_synthetic_center_generator_is_deterministic(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = generate_dataset(first_dir)
    second = generate_dataset(second_dir)

    first_orders = json.loads((first_dir / "order_arrivals.json").read_text(encoding="utf-8"))
    second_orders = json.loads((second_dir / "order_arrivals.json").read_text(encoding="utf-8"))

    assert first["seed"] == 20260521
    assert second["seed"] == 20260521
    assert first_orders == second_orders
    assert 480 <= len(first_orders["orders"]) <= 520
    assert all(order["detection_route"] for order in first_orders["orders"])


def test_synthetic_center_routes_have_variable_durations_and_shared_equipment(tmp_path):
    output_dir = tmp_path / "routes"

    generate_dataset(output_dir)
    orders = json.loads((output_dir / "order_arrivals.json").read_text(encoding="utf-8"))["orders"]
    project_catalog = json.loads((output_dir / "project_catalog.json").read_text(encoding="utf-8"))
    equipment_catalog = json.loads((output_dir / "equipment_catalog.json").read_text(encoding="utf-8"))
    equipment_types = {item["equipment_type"] for item in equipment_catalog["equipment_types"]}
    profiles = {
        step["project_id"]: step
        for flow in project_catalog["certification_flows"]
        for step in flow["steps"]
    }

    route_lengths = [len(order["detection_route"]) for order in orders]
    durations_by_project: dict[str, set[int]] = {}
    equipment_sequences = []
    for order in orders:
        assert [step["sequence"] for step in order["detection_route"]] == list(range(1, len(order["detection_route"]) + 1))
        equipment_sequences.append(tuple(step["equipment_type"] for step in order["detection_route"]))
        for step in order["detection_route"]:
            assert step["equipment_type"] in equipment_types
            profile = profiles[step["project_id"]]
            assert profile["t_min"] <= step["duration_minutes"] <= profile["t_max"]
            durations_by_project.setdefault(step["project_type"], set()).add(step["duration_minutes"])

    assert max(route_lengths) >= 4
    assert len(set(equipment_sequences)) >= 3
    assert any(len(durations) > 1 for durations in durations_by_project.values())
    assert sum(1 for sequence in equipment_sequences if "emc_tester" in sequence) > 1


def test_large_synthetic_center_generator_creates_larger_reproducible_sample(tmp_path):
    first_dir = tmp_path / "large-first"
    second_dir = tmp_path / "large-second"

    first = generate_dataset(first_dir, config=LARGE_CONFIG)
    second = generate_dataset(second_dir, config=LARGE_CONFIG)
    first_orders = json.loads((first_dir / "order_arrivals.json").read_text(encoding="utf-8"))
    second_orders = json.loads((second_dir / "order_arrivals.json").read_text(encoding="utf-8"))

    assert first["seed"] == LARGE_CONFIG["seed"]
    assert second["seed"] == LARGE_CONFIG["seed"]
    assert first_orders == second_orders
    assert len(first_orders["orders"]) == LARGE_CONFIG["target_order_count"]

    report = validate_dataset(first_dir, working_dir=tmp_path / "large-validation", integration_order_limit=50)
    assert report["summary"]["failed"] == 0
    integration = next(check for check in report["checks"] if check["name"] == "api_queue_integration")
    assert integration["evidence"]["integration_order_limit"] == 50


def test_synthetic_center_dataset_validates_static_files(tmp_path):
    dataset_dir = Path(__file__).resolve().parents[1] / "data" / "scenario_synthetic_center"

    report = validate_dataset(dataset_dir=dataset_dir, working_dir=tmp_path)

    assert report["summary"]["failed"] == 0
    assert {check["name"] for check in report["checks"]} >= {
        "required_files",
        "order_volume",
        "distribution_ranges",
        "catalog_references",
        "operations_constraints",
        "rag_knowledge",
        "api_queue_integration",
        "agent_handoff",
    }
