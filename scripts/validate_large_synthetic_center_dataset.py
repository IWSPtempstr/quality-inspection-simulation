from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_synthetic_center_dataset import validate_dataset


LARGE_DATASET_DIR = PROJECT_ROOT / "data" / "scenario_synthetic_center_large"


def main() -> None:
    report = validate_dataset(
        LARGE_DATASET_DIR,
        working_dir=PROJECT_ROOT / "data" / "_synthetic_large_validation_tmp",
        integration_order_limit=500,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["summary"]["failed"] else 0)


if __name__ == "__main__":
    main()
