# Phase 5 / I6 final cleanup audit

Date: 2026-07-17

This audit records the final cleanup verification executed after the approved
I5 legacy-runtime deletion scope was applied. It separates:

- assets that were eligible for automatic cleanup under I6;
- assets intentionally kept as formal runtime, contract, test, deploy, or
  evidence material;
- remaining review-only assets that were intentionally not deleted.

## In-scope automatic cleanup result

I6 inspected the approved automatic-cleanup scope and found no remaining
matches in the current worktree. As a result, I6 performed no additional
deletions.

| Path pattern | Item type | Result | Rationale |
| --- | --- | --- | --- |
| `.ruff_cache/**` | tool cache | not present | No repo-root Ruff cache remained after the post-cutover worktree review. |
| `.mypy_cache/**` | tool cache | not present | No repo-root mypy cache remained. |
| `.pytest_cache/**` | tool cache | not present | No repo-root pytest cache remained. |
| `**/__pycache__` | Python bytecode | not present | No Python bytecode cache directories remained outside excluded dependency trees. |
| `data/_validation_tmp/**` | temporary validation outputs | not present | No temporary validation directory remained. |
| `data/_synthetic_validation_tmp/**` | temporary validation outputs | not present | No temporary synthetic validation directory remained. |
| `data/_synthetic_large_validation_tmp/**` | temporary validation outputs | not present | No temporary large synthetic validation directory remained. |
| `data/_optimized_scheduling_eval_tmp/**` | temporary evaluation outputs | not present | No temporary evaluation directory remained. |

## Kept assets

These assets remain and were intentionally not treated as cleanup debt:

| Path | Item type | Current purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `services/api-go/**` | current runtime | production Go API/worker | keep | Formal production runtime. |
| `services/scheduler-py/**` | current runtime | production scheduler service | keep | Formal production runtime. |
| `services/ai-py/**` | current runtime | production AI boundary | keep | Formal production runtime. |
| `contracts/**` | contracts | authoritative OpenAPI definitions | keep | Current contract source of truth. |
| `deploy/**` | deployment assets | Phase 5 deployment/cutover deliverables | keep | Formal delivery asset. |
| `tests/**` | regression evidence | unit/integration/E2E verification | keep | Official regression coverage. |
| `docs/**` | audit/migration/product evidence | acceptance and migration evidence | keep | Formal project evidence. |
| `data/evaluation/**` | offline evaluation corpus | historical evaluation inputs | keep | Evidence and study asset. |
| `data/evaluation_reports/**` | generated reports | historical scheduling experiment outputs | keep | Evidence artifact. |
| `data/mechanism_validation/**` | validation fixtures | controlled validation inputs | keep | Useful verification asset. |
| `data/scenario_synthetic_center*/**` | synthetic datasets | fixture corpora and offline validation inputs | keep | Controlled fixture asset. |

## Remaining review-only assets

These assets intentionally remain after I5/I6 and require later explicit
review rather than automatic deletion:

| Path | Item type | Current purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `config/**` | deferred review asset | old monolith settings/reference surface | review | Deferred by the approved I5 amendment. |
| `db/**` | deferred review asset | old SQLAlchemy schema/repository layer | review | Deferred by the approved I5 amendment. |
| `domain/**` | deferred review asset | old Pydantic domain layer | review | Deferred by the approved I5 amendment. |
| `prototype/**` | deferred review asset | historical prototype assets | review | Deferred by the approved I5 amendment. |
| `README.md` | deferred review doc | still documents historical monolith startup | review | Amendment explicitly deferred it. |
| `.mcp.json` | deferred review config | tooling/MCP config | review | Amendment explicitly deferred it. |
| `openapitools.json` | deferred review config | root-level tooling config | review | Amendment explicitly deferred it. |
| `services/dataset_replay_service.py` | deferred review code | legacy/research support service | review | Amendment explicitly deferred it. |
| `services/evaluation_gate.py` | deferred review code | legacy/research support logic | review | Amendment explicitly deferred it. |
| `services/evaluation_service.py` | deferred review code | legacy/research support logic | review | Amendment explicitly deferred it. |
| `services/monitoring_service.py` | deferred review code | historical monitoring support | review | Amendment explicitly deferred it. |
| `services/schedule_formatter.py` | deferred review code | historical formatting support | review | Amendment explicitly deferred it. |
| `services/schedule_metrics.py` | deferred review code | historical metrics support | review | Amendment explicitly deferred it. |
| `scripts/**` | deferred review scripts | offline generation/validation/evaluation tooling | review | Amendment explicitly deferred it. |
| `data/simulation.db` | deferred review database | historical SQLite runtime DB | review | Amendment explicitly deferred it. |
| `apps/web/node_modules/**` | local install tree | frontend dependency install | review | Workspace/tooling choice, not product cleanup. |
| `services/api-go/node_modules/**` | local install tree | Go OpenAPI generation tooling install | review | Workspace/tooling choice, not product cleanup. |

## Verification summary

- The approved I5 exact delete scope was removed and no broader legacy paths
  were deleted by inference.
- No deferred-review asset listed above was deleted during I5/I6.
- No current rebuild runtime, contract, deploy, test, or audit path was
  deleted during I5/I6.
- The explicit cache and temporary-output paths named above were not present
  in the current worktree when I6 verification ran, so no extra cleanup
  beyond the approved I5 runtime deletion was necessary.
