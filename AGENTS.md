<!-- code-review-graph MCP tools -->
## Code Exploration

This project has a code-review-graph knowledge graph. Use graph tools before
grep/read-style exploration:

- `get_minimal_context` for task entry.
- `query_graph` for callers, callees, imports, tests, and file summaries.
- `get_impact_radius` / `detect_changes` for review and blast-radius checks.
- Fall back to `rg` and file reads only when graph output is insufficient.

## LLM Agent Safety Boundary

LLM output must not directly create orders, decide schedules, reserve equipment,
or mutate resource state. All writes must go through deterministic API/service
paths with permission checks.

Current Agent tasks:

| Capability | Agent | Task Type | Permission |
| --- | --- | --- | --- |
| RAG answer synthesis | `rag_retriever` | `search_knowledge` | `schedule:read` |
| Schedule explanation | `queue_scheduler` | `explain_schedule` | `schedule:read` |
| Exception analysis | `exception_analyzer` | `analyze_exception` | `schedule:read` |
| Notification copy enhancement | `notification_agent` | `generate_notifications` | `schedule:write` |
| Natural-language order draft | `order_manager` | `draft_order_from_text` | `orders:read` |
| Detection project recommendation | `project_identifier` | `identify_projects` | `schedule:read` |
| Natural-language task routing | `orchestrator` | `route_user_query` | `schedule:read` |

Safety invariants:

- `draft_order_from_text` only returns a draft; it never writes an order.
- `route_user_query` only returns a recommendation; it never executes it.
- `identify_projects` must preserve deterministic required-project checks.
- LLM failure or missing API key must return deterministic fallback with
  `mode = "deterministic_fallback"` when the task response has a mode field.

## Harness Implementation Anchors

- `DEV_SPEC.md` is the implementation authority for Harness optimization.
- `agents/llm_gateway.py` owns optional LLM JSON call normalization.
- `agents/validators.py` owns pure Agent output validation helpers.
- `agents/trace_utils.py` owns trace/tool/token aggregation helpers.
- `services/evaluation_gate.py` owns deterministic evaluation gate logic.
- `services/evaluation_service.py::failed_trace_eval_records()` converts failed
  traces into sanitized regression cases.

## Verification Commands

Use targeted tests while changing a subsystem, then run full regression:

```bash
python -m pytest tests/test_agent_llm_and_mcp_adapter.py -q
python -m pytest tests/test_agent_evaluation_and_tracing.py -q
python -m pytest tests/test_api_and_agents.py -q
python -m pytest tests/test_queue_service.py -q
python -m pytest -q
```

## Reference Documents

- `README.md`: product and architecture overview.
- `Harness.md`: Harness theory and study notes.
- `docs/harness_memory_cleanup.md`: durable-memory cleanup rationale.
