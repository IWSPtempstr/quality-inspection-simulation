from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_synthetic_center_dataset import LARGE_CONFIG, generate_dataset


LARGE_DATASET_DIR = PROJECT_ROOT / "data" / "scenario_synthetic_center_large"


def main() -> None:
    report = generate_dataset(LARGE_DATASET_DIR, config=LARGE_CONFIG)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
