from pathlib import Path
import subprocess
import sys

from scripts.validate_system_mechanism import run_validation


def test_minimal_dataset_validates_system_mechanism(tmp_path):
    dataset_dir = Path(__file__).resolve().parents[1] / "data" / "mechanism_validation"

    report = run_validation(dataset_dir=dataset_dir, working_dir=tmp_path)

    assert report["summary"]["failed"] == 0
    assert report["summary"]["passed"] >= 6
    assert report["dataset"] == str(dataset_dir)
    assert {check["name"] for check in report["checks"]} >= {
        "dataset_loaded",
        "rag_reindex_and_search",
        "order_crud_ingestion",
        "queue_rebuild_priority_capacity_sequence",
        "schedule_persistence",
        "agent_handoff_and_mcp_monitoring",
    }


def test_validation_script_can_run_as_cli():
    project_root = Path(__file__).resolve().parents[1]
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(project_root / "scripts" / "validate_system_mechanism.py")],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert '"failed": 0' in result.stdout
