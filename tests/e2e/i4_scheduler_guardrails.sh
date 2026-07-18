#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PYTHONPATH="${ROOT_DIR}/services/scheduler-py/src" \
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning \
python "${ROOT_DIR}/tests/e2e/i4_scheduler_guardrails.py"
