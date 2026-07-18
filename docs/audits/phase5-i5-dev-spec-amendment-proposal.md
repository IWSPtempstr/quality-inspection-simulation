# Proposed DEV_SPEC amendment for Phase 5 / I5

Date: 2026-07-17

This proposal does not delete files. It prepares the exact-file amendment that
`DEV_SPEC.md` requires before Phase 5 / I5 can execute legacy runtime removal.

## Proposed amendment text

Add the following text under Phase 5 / I5 in `DEV_SPEC.md` before any deletion
work starts:

> ### I5 approved legacy runtime deletion scope
>
> I5 may delete only the legacy runtime paths listed below, and only after the
> cutover rollback window ends and I4 acceptance remains green in the current
> worktree.
>
> Exact delete scope:
>
> - `app.py`
> - `requirements.txt`
> - `api/**`
> - `web/**`
> - `agents/**`
> - `mcp_server/**`
> - `rag/__init__.py`
> - `rag/retriever.py`
> - `rag/vector_store.py`
> - `rag/index/index.faiss`
> - `rag/index/metadata.json`
> - `services/__init__.py`
> - `services/cp_sat_schedule_service.py`
> - `services/llm_client.py`
> - `services/mcp_client.py`
> - `services/notification_service.py`
> - `services/queue_service.py`
> - `services/scheduler_service.py`
> - `services/security_service.py`
> - `services/simulation_service.py`
> - `services/tool_client.py`
>
> Explicit non-delete scope for this amendment:
>
> - `services/api-go/**`
> - `services/scheduler-py/**`
> - `services/ai-py/**`
> - `contracts/**`
> - `deploy/**`
> - `tests/**`
> - `docs/**`
> - `data/evaluation/**`
> - `data/evaluation_reports/**`
> - `data/mechanism_validation/**`
> - `data/scenario_synthetic_center*/**`
>
> Deferred review items not covered by this amendment:
>
> - `config/**`
> - `db/**`
> - `domain/**`
> - `prototype/**`
> - `README.md`
> - `.mcp.json`
> - root `openapitools.json`
> - `services/dataset_replay_service.py`
> - `services/evaluation_gate.py`
> - `services/evaluation_service.py`
> - `services/monitoring_service.py`
> - `services/schedule_formatter.py`
> - `services/schedule_metrics.py`
> - `scripts/**`
> - `data/simulation.db`
>
> I5 must update `spec.md` with the exact commands run, the deleted paths, and
> any follow-up review required for the deferred items. I6 must audit temporary
> caches, generated artifacts, and any remaining review-only legacy assets
> after the approved I5 deletion completes.

## Why this is the minimum safe amendment

- The delete scope is limited to the old FastAPI/Jinja/LangGraph/MCP/FAISS
  runtime that `DEV_SPEC.md` explicitly replaced.
- The proposal avoids silently deleting old SQLAlchemy/data/replay assets that
  may still support migration comparison or offline validation.
- The proposal preserves current rebuild runtime, contracts, tests, deploy
  assets, audit evidence, and synthetic fixtures.

## Current evidence for the deferred review set

The deferred items are intentionally excluded from the exact delete scope
because current repository evidence still shows active reference or historical
validation value:

- `services/evaluation_gate.py` and `services/evaluation_service.py` are still
  named in `AGENTS.md`, `docs/harness_memory_cleanup.md`, and the legacy
  regression suite under `tests/`.
- `services/schedule_formatter.py` and `services/schedule_metrics.py` are still
  imported by legacy `api/**`, `services/**`, and historical tests.
- `services/dataset_replay_service.py` is still mounted by the legacy `app.py`
  and referenced by `api/datasets.py` plus profile tests.
- `config/**`, `db/**`, and `domain/**` are still described by the root
  `README.md` and remain part of the legacy comparison surface documented in
  `CODE_REVIEW_GRAPH.md`.
- `scripts/validate_system_mechanism.py` and
  `scripts/evaluate_optimized_scheduling.py` are still referenced by tests or
  data-readme material, so deleting them would also require an explicit
  decision about their validation role.

These references do not make the deferred set production runtime. They only
show that the current worktree still treats them as migration, validation, or
historical-reference assets, so a stricter follow-up amendment should decide
them explicitly rather than by inference during I5 execution.

## Suggested execution order after approval

1. Copy the approved text into `DEV_SPEC.md`.
2. Execute I5 deletions only within the exact delete scope above.
3. Update `spec.md` with the removed paths and verification commands.
4. Run I6 final cleanup audit for caches, generated artifacts, and deferred
   review items that still remain in the repository.
