# Phase 5 / I6 pre-cleanup audit

Date: 2026-07-17

This is a pre-cleanup audit for Phase 5 / I6. It does not delete anything.
Its purpose is to separate true cleanup debt from:

- current rebuild runtime assets that must stay;
- Phase 5 / I5 legacy-runtime deletion candidates that require the approved
  delete scope first;
- offline evidence, synthetic fixtures, and generated reports that are still
  useful after cutover.

## Cleanup candidates after I5 completes

| Path | Item type | Current purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `.ruff_cache/**` | tool cache | local Ruff cache at repo root | delete | Generated analyzer cache, not source or evidence. |
| `.npm-cache/**` | package cache | local npm cache at repo root | delete | Generated package cache, not a deliverable. |
| `apps/web/.npm-cache/**` | package cache | frontend-local npm cache | delete | Generated cache that should not survive final cleanup. |
| `services/ai-py/.ruff_cache/**` | tool cache | AI service Ruff cache | delete | Generated analysis artifact. |
| `services/ai-py/.mypy_cache/**` | tool cache | AI service mypy cache | delete | Generated analysis artifact. |
| `services/ai-py/.pytest_cache/**` | tool cache | AI service pytest cache | delete | Generated test-run artifact. |
| `services/scheduler-py/.ruff_cache/**` | tool cache | scheduler Ruff cache | delete | Generated analysis artifact. |
| `services/scheduler-py/.mypy_cache/**` | tool cache | scheduler mypy cache | delete | Generated analysis artifact. |
| `services/scheduler-py/.pytest_cache/**` | tool cache | scheduler pytest cache | delete | Generated test-run artifact. |
| `services/ai-py/**/__pycache__` | Python bytecode | runtime/import cache | delete | Regenerated automatically; not source of record. |
| `services/scheduler-py/**/__pycache__` | Python bytecode | runtime/import cache | delete | Regenerated automatically; not source of record. |
| `tests/e2e/oidc-stub/__pycache__` | Python bytecode | local test helper cache | delete | Generated test artifact. |
| `tests/e2e/partner-recorder/__pycache__` | Python bytecode | local test helper cache | delete | Generated test artifact. |
| `data/_validation_tmp/**` | temporary validation database/index | scratch validation outputs | review | Likely disposable, but confirm no active validation flow still expects them. |
| `data/_synthetic_validation_tmp/**` | temporary validation database/index | scratch synthetic validation outputs | review | Same as above; clearly temporary by naming. |
| `data/_synthetic_large_validation_tmp/**` | temporary validation database/index | scratch large-validation outputs | review | Same as above; clearly temporary by naming. |
| `data/_optimized_scheduling_eval_tmp/**` | temporary evaluation database/index | scratch evaluation outputs | review | Temporary by naming, but may still support offline comparisons if the user wants to preserve them. |

## Keep as formal evidence or current runtime

| Path | Item type | Current purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `services/api-go/**` | current runtime | production rebuild Go API and worker | keep | Formal production runtime. |
| `services/scheduler-py/**` | current runtime | production rebuild scheduler service | keep | Formal production runtime. |
| `services/ai-py/**` | current runtime | production rebuild AI boundary | keep | Formal production runtime. |
| `contracts/**` | contracts | current OpenAPI contract source | keep | Authoritative contract surface. |
| `deploy/**` | deployment assets | current deployment/cutover skeleton | keep | Phase 5 deliverable. |
| `tests/**` | regression evidence | unit/integration/E2E verification | keep | Official regression coverage must not be flagged as disposable. |
| `docs/**` | audit/migration/product evidence | acceptance and migration records | keep | Formal evidence set for delivery and cutover. |
| `data/evaluation/**` | offline evaluation corpus | historical evaluation cases | keep | Evidence and research input, not runtime trash. |
| `data/evaluation_reports/**` | generated reports | historical optimization/evaluation outputs | keep | User-visible evidence artifacts. |
| `data/mechanism_validation/**` | validation fixtures | controlled validation inputs | keep | Explicitly useful for mechanism verification. |
| `data/scenario_synthetic_center*/**` | synthetic datasets | fixture corpora and offline validation inputs | keep | Controlled fixture assets, not cleanup debt by default. |
| `apps/web/node_modules/**` | installed dependencies | current frontend validation/runtime toolchain support | review | Generated dependencies, but deleting them is a workspace/tooling choice rather than a phase-end product cleanup decision. |
| `services/api-go/node_modules/**` | installed generator dependencies | current Go OpenAPI generation toolchain | review | Generated dependencies; keep unless the user wants a stricter local-workspace cleanup. |

## Review-only assets that depend on I5 scope

These are not I6 cleanup deletions yet. They belong to either the approved I5
legacy-runtime delete scope or its deferred review set.

| Path | Item type | Current purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `app.py`, `requirements.txt`, `api/**`, `web/**`, `agents/**`, `mcp_server/**`, selected `rag/**`, selected legacy `services/*.py` | legacy runtime | old monolith runtime and removed capabilities | review under I5 | Must follow the approved I5 delete scope, not ad hoc cleanup. |
| `config/**`, `db/**`, `domain/**`, `prototype/**`, `scripts/**`, `README.md`, `.mcp.json`, root `openapitools.json`, `data/simulation.db`, deferred legacy `services/*.py` | mixed legacy/reference assets | may still support validation, migration comparison, or historical reference | review under I5/I6 | These need explicit human judgment after the approved I5 deletion executes. |

## Notes from current-state inspection

- The repo root still contains the old monolith entrypoint `app.py` and
  `requirements.txt`, but those are governed by I5, not by I6 cleanup.
- The old runtime still references SQLite (`data/simulation.db`), MCP, FAISS,
  LangGraph, and Jinja-based debug panels. Those findings support the I5 legacy
  deletion proposal, not an immediate I6 cleanup action.
- No production rebuild source path was flagged here as disposable merely
  because it is recent or small.

## Minimum next step

1. Approve and apply the I5 deletion amendment.
2. Execute I5 only within that approved delete scope.
3. Re-run this audit against the post-I5 worktree.
4. Delete cache/bytecode/temp artifacts that remain appropriate to remove.
