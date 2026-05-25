from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.scheduling_optimization_utils import derive_optimized_dataset


SOURCE_DIR = PROJECT_ROOT / "data" / "scenario_synthetic_center_large"
TARGETS = {
    "balanced": PROJECT_ROOT / "data" / "scenario_synthetic_center_balanced_5000",
    "highload": PROJECT_ROOT / "data" / "scenario_synthetic_center_highload_5000",
}


def main() -> None:
    reports = {
        scenario: derive_optimized_dataset(SOURCE_DIR, output_dir, scenario)
        for scenario, output_dir in TARGETS.items()
    }
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
