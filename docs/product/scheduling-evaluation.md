# Scheduling Evaluation (S5)

This report defines the controlled-fixture regression harness required by S5.
It is intentionally offline and fixture-only: it does not replay public API
traffic, browser flows, historical datasets, or partner callbacks.

## Commands

Run from `/home/work/workproject2/project/services/scheduler-py`:

- `PYTHONPATH=src /root/anaconda3/bin/conda run --no-capture-output -n agent-learning ruff check .`
- `PYTHONPATH=src /root/anaconda3/bin/conda run --no-capture-output -n agent-learning mypy src`
- `PYTHONPATH=src /root/anaconda3/bin/conda run --no-capture-output -n agent-learning pytest -q`

## Controlled fixtures

| Fixture | Purpose | Expected evidence |
| --- | --- | --- |
| `hard_constraints` | Exercise a feasible CP-SAT snapshot with ordered work and shared resources. | Zero hard-constraint violations and no fallback use. |
| `frozen_invariance` | Hold one frozen step fixed while scheduling later work. | Frozen start/end/resource tuple remains unchanged in both CP-SAT and deterministic fallback. |
| `fallback_determinism` | Re-run deterministic fallback for the same immutable snapshot. | Identical normalized candidate hash across repeated runs. |
| `equal_sla_change_bias` | Compare CP-SAT and fallback on an equal-SLA snapshot with preserved formal starts. | Equal lateness metrics, but CP-SAT reports fewer formal-start changes than fallback. |

## Validation scope

The harness derives and checks:

- scheduled step identity, order binding, and positive duration
- per-order precedence
- equipment capacity and employee non-overlap
- employee skill/role eligibility
- employee shift windows and unavailability
- equipment maintenance/failure blackout windows
- frozen-step invariance
- lateness and weighted lateness
- formal-start change count

## Explicit non-goals

S5 does not claim or gate on:

- historical-SLA baselines
- solve rate
- latency
- dataset-derived metrics
- UI, API, or callback replay
