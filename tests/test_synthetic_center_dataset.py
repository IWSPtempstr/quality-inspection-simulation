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
