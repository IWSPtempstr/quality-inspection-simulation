# Harness Memory Cleanup Proposal

## Goal

Keep project-level durable memory useful for agent workers by separating
project-specific operating rules from general Harness theory.

This is a proposal only. It does not modify `AGENTS.md`.

## Keep In Agent Memory

`AGENTS.md` should retain facts that directly affect day-to-day agent behavior:

- Use code-review-graph MCP tools before grep/read-style exploration.
- LLM Agent safety boundary: LLM output must not directly create orders, decide
  schedules, reserve equipment, or mutate resource state.
- Deterministic fallback semantics: missing API key or failed LLM calls return
  deterministic fallback with `mode` equal to `deterministic_fallback`.
- Allowed v1/v2 Agent task types and their write/read safety posture.
- Core verification entry points:
  - `python -m pytest tests/test_agent_llm_and_mcp_adapter.py -q`
  - `python -m pytest tests/test_agent_evaluation_and_tracing.py -q`
  - `python -m pytest tests/test_queue_service.py -q`
  - `python -m pytest -q` for full regression.
- Current Harness implementation anchors:
  - `DEV_SPEC.md` is the implementation authority for Harness optimization.
  - `agents/llm_gateway.py` owns optional LLM JSON call normalization.
  - `agents/validators.py` owns pure Agent output validation helpers.
  - `agents/trace_utils.py` owns trace/tool/token aggregation helpers.
  - `services/evaluation_gate.py` owns deterministic evaluation gate logic.

## Move Out Of Agent Memory

The following content is valuable reference material but should stay in
`Harness.md` or README-style documentation instead of being injected into every
agent session:

- General definitions such as `Agent - Model = Harness`.
- Long-form explanations of Prompt Engineering, Context Engineering, and
  Harness Engineering history.
- Interview-style Q&A material.
- Generic recommendations that are not specific to this repository.
- Duplicate architecture sections.

## Suggested AGENTS.md Shape

1. `code-review-graph` workflow.
2. Project safety rules for LLM Agents.
3. Current Agent task matrix.
4. Fallback and trace semantics.
5. Verification commands.
6. Links to deeper documents:
   - `DEV_SPEC.md` for implementation governance.
   - `Harness.md` for Harness theory and study notes.
   - `README.md` for product and architecture overview.

## Review Checklist

Before editing `AGENTS.md`, verify:

- Every retained item is project-specific and actionable.
- No generic Harness theory remains in the default injected memory.
- No API examples are duplicated if README already covers them.
- The file stays short enough to scan before each task.
