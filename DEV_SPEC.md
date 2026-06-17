# Harness Optimization DEV_SPEC

> This spec is the authority for all implementation work. Agent workers may
> only modify files explicitly listed in the active task. Any architecture,
> module, dependency, or file outside this document requires a spec update and
> human review before implementation.

## 1. Goal

Improve the project as a Harness-engineered multi-agent simulation system:
make Agent execution more bounded, testable, observable, and reviewable while
preserving current business behavior and public API compatibility.

The implementation must prioritize deterministic validation over AI self
assessment. Completion is judged by external programs: `pytest`, optional
`mypy` when configured, and project evaluation gates.

## 2. Non-Goals

- Do not add new business capabilities unless a task below explicitly defines
  the interface and tests.
- Do not let LLM output create orders, change schedules, reserve equipment, or
  mutate resource state directly.
- Do not replace the current FastAPI, SQLAlchemy, LangGraph, FAISS, MCP, or
  pytest stack.
- Do not introduce new runtime dependencies without a spec update and human
  approval.
- Do not rewrite large modules opportunistically. Refactors must preserve
  behavior and stay inside task-owned file scopes.

## 3. Current Architecture Baseline

The project is organized as:

- `api/`: FastAPI routes.
- `agents/graph.py`: LangGraph Agent runner, task routing, LLM/fallback logic,
  validation, handoffs, and trace metadata.
- `services/`: scheduling, LLM client, MCP adapter, evaluation, notification,
  monitoring, dataset replay, security.
- `rag/`: knowledge retrieval and vector store.
- `db/`: SQLAlchemy models and repositories.
- `domain/`: Pydantic schemas and enums.
- `tests/`: pytest coverage for API, Agent, scheduling, RAG, MCP, datasets,
  notifications, and evaluation.

Graph-derived risk hotspots at spec time:

- `agents/graph.py::AgentGraphRunner`: large single-runner Agent Harness.
- `services/queue_service.py::QueueService`: high-degree scheduling hub.
- `services/cp_sat_schedule_service.py`: solver complexity and fallback risk.
- `services/evaluation_service.py`: quality gate and trace summary logic.
- `app.py::create_app`: app construction bridge.

## 4. Harness Execution Protocol

Every implementation task must follow this protocol.

1. **Task isolation**
   - One task is executed by one fresh worker session.
   - The worker reads this spec and only the files named in the active task.
   - After the task final response, the worker is closed.

2. **File permission boundary**
   - A worker may modify only files listed under `Allowed writes`.
   - A worker may read files listed under `Required reads` plus direct imports
     needed to understand those files.
   - Creating files not listed under `Allowed writes` is a spec violation.

3. **Program-driven judgement**
   - A task is not complete until its required commands exit successfully.
   - AI-written explanations do not substitute for passing tests.
   - If a task fails verification, the worker may attempt at most three fix
     rounds. After three failed rounds, stop and request human review.

4. **Code review after every task**
   - Review must check: spec compliance, file-scope compliance, API
     compatibility, test adequacy, and unintended behavior changes.
   - The next task cannot start until review findings are resolved or accepted.

5. **Commits**
   - Each task should be committed independently after verification and review.
   - Commit message format: `harness: <task id> <short summary>`.
   - Do not commit unrelated existing workspace changes.

## 5. Public Interface Compatibility

The following public routes and response semantics must remain compatible unless
a later spec revision explicitly changes them:

- `POST /api/agent/run`
- `POST /api/evaluation/run`
- Agent task types:
  - `search_knowledge`
  - `explain_schedule`
  - `analyze_exception`
  - `generate_notifications`
  - `draft_order_from_text`
  - `identify_projects`
  - `route_user_query`
- LLM mode field values:
  - `llm`
  - `deterministic_fallback`
- Trace metadata must continue to include enough information for visited
  agents, handoffs, tool calls, fallback state, latency, and token usage.

## 6. Target Module Boundaries

The target architecture decomposes the Agent Harness without changing API
surface behavior.

### 6.1 Agent Runner

Responsibility:

- Own LangGraph construction and node orchestration.
- Delegate LLM calls, validation, and trace aggregation to helper modules.
- Preserve existing task routing behavior.

Long-term target files:

- `agents/graph.py`
- `agents/llm_gateway.py`
- `agents/validators.py`
- `agents/trace_utils.py`
- `agents/task_contracts.py`

### 6.2 LLM Gateway

Responsibility:

- Wrap `LlmClientProtocol.chat_json()`.
- Normalize success/failure output.
- Record fallback reason, mode, model, raw token usage, and tool-call metadata.
- Never apply business mutations.

Target interface:

```python
@dataclass(frozen=True)
class LlmGatewayResult:
    content: dict[str, Any]
    mode: str
    fallback_used: bool
    error: str | None
    metadata: dict[str, Any]


class LlmGateway:
    def chat_json(
        self,
        *,
        agent_name: str,
        client: LlmClientProtocol | None,
        messages: list[dict[str, str]],
        fallback: Callable[[str | None], dict[str, Any]],
        required_keys: set[str] | None = None,
    ) -> LlmGatewayResult:
        ...
```

### 6.3 Validators

Responsibility:

- Validate allowed route recommendations.
- Validate order draft wrapper shape.
- Validate project recommendations, schedule explanation, knowledge answer, and
  exception analysis.
- Return deterministic fallback-compatible failures instead of raising from
  normal model bad output.

Target interface:

```python
def validate_route_recommendation(value: Mapping[str, Any]) -> bool: ...
def valid_knowledge_answer(value: Mapping[str, Any]) -> bool: ...
def valid_schedule_explanation(value: Mapping[str, Any]) -> bool: ...
def valid_exception_analysis(value: Mapping[str, Any]) -> bool: ...
```

### 6.4 Trace Utilities

Responsibility:

- Aggregate tool calls and token usage.
- Convert Agent state into JSON-ready trace metadata.
- Provide deterministic shape for evaluation.

Target interface:

```python
def agent_tool_calls(state: Mapping[str, Any]) -> list[dict[str, Any]]: ...
def agent_token_usage(state: Mapping[str, Any]) -> dict[str, int]: ...
def aggregate_token_usage(items: Iterable[Mapping[str, Any]]) -> dict[str, int]: ...
```

### 6.5 Evaluation Gate

Responsibility:

- Convert offline evaluation and online trace metrics into machine-checkable
  pass/fail status.
- Report threshold failures without relying on LLM judgement.

Target interface:

```python
@dataclass(frozen=True)
class EvaluationGateResult:
    passed: bool
    failures: list[str]
    metrics: dict[str, Any]
```

## 7. Required Test Floor

The implementation must add or preserve at least:

- 6 unit tests
- 3 integration tests
- 1 E2E test

Minimum coverage topics:

1. Unit: route whitelist validation.
2. Unit: LLM gateway deterministic fallback on missing client.
3. Unit: LLM gateway fallback on invalid/missing required keys.
4. Unit: trace token aggregation.
5. Unit: evaluation gate threshold failure.
6. Unit: schedule or SLA helper behavior when extracted.
7. Integration: `/api/agent/run` read-only task does not trigger writes.
8. Integration: offline evaluation returns gate-compatible metrics.
9. Integration: trace failure can be converted to an eval-style record.
10. E2E: agent request runs through route, fallback/LLM handling, trace
    metadata, and evaluation-visible output.

## 8. Verification Commands

Use commands that exist in the repository at execution time.

Base commands:

```bash
pytest tests/test_agent_llm_and_mcp_adapter.py -q
pytest tests/test_agent_evaluation_and_tracing.py -q
pytest tests/test_api_and_agents.py -q
pytest tests/test_queue_service.py -q
```

Full command:

```bash
pytest -q
```

Type checking:

- No mypy configuration exists at spec time.
- Do not add mypy as a required gate until a spec task adds configuration and
  dependency policy.

## 9. Task Plan

### Task H0: Spec Baseline

Purpose:

- Establish this file as the implementation authority.

Required reads:

- `Harness.md`
- `README.md`
- `requirements.txt`
- Existing test file list under `tests/`

Allowed writes:

- `DEV_SPEC.md`

Verification:

```bash
test -f DEV_SPEC.md
python -m pytest tests/test_agent_llm_and_mcp_adapter.py -q
```

Review checklist:

- Spec includes stages, file boundaries, interfaces, tests, and verification.
- Spec does not authorize broad rewrites.

### Task H1: Extract Trace Utilities

Purpose:

- Move trace aggregation helpers out of `AgentGraphRunner` without changing
  behavior.

Required reads:

- `agents/graph.py`
- `tests/test_agent_llm_and_mcp_adapter.py`
- `tests/test_agent_evaluation_and_tracing.py`

Allowed writes:

- `agents/trace_utils.py`
- `agents/graph.py`
- `tests/test_agent_llm_and_mcp_adapter.py`

Interface:

```python
def json_ready(value: Any) -> Any: ...
def agent_tool_calls(state: Mapping[str, Any]) -> list[dict[str, Any]]: ...
def agent_token_usage(state: Mapping[str, Any]) -> dict[str, int]: ...
def aggregate_token_usage(items: Iterable[Mapping[str, Any]]) -> dict[str, int]: ...
```

Verification:

```bash
pytest tests/test_agent_llm_and_mcp_adapter.py -q
```

Review checklist:

- `AgentGraphRunner` response shape is unchanged.
- Existing private methods either delegate to `trace_utils` or are removed only
  when no longer referenced.

### Task H2: Extract Agent Validators

Purpose:

- Move pure validation helpers out of `AgentGraphRunner`.

Required reads:

- `agents/graph.py`
- `domain/schemas.py`
- `tests/test_agent_llm_and_mcp_adapter.py`

Allowed writes:

- `agents/validators.py`
- `agents/graph.py`
- `tests/test_agent_llm_and_mcp_adapter.py`

Interface:

```python
def validate_route_recommendation(value: Mapping[str, Any]) -> bool: ...
def valid_knowledge_answer(value: Mapping[str, Any]) -> bool: ...
def valid_schedule_explanation(value: Mapping[str, Any]) -> bool: ...
def valid_exception_analysis(value: Mapping[str, Any]) -> bool: ...
```

Verification:

```bash
pytest tests/test_agent_llm_and_mcp_adapter.py -q
pytest tests/test_api_and_agents.py -q
```

Review checklist:

- Allowed task/agent combinations remain whitelisted.
- Bad LLM output still falls back deterministically.

### Task H3: Introduce LLM Gateway

Purpose:

- Centralize LLM JSON call handling and fallback metadata.

Required reads:

- `agents/graph.py`
- `services/llm_client.py`
- `config/settings.py`
- `tests/test_agent_llm_and_mcp_adapter.py`

Allowed writes:

- `agents/llm_gateway.py`
- `agents/graph.py`
- `tests/test_agent_llm_and_mcp_adapter.py`

Interface:

Use `LlmGateway` and `LlmGatewayResult` from section 6.2. The gateway must not
perform business writes or call repositories.

Verification:

```bash
pytest tests/test_agent_llm_and_mcp_adapter.py -q
pytest tests/test_agent_evaluation_and_tracing.py -q
```

Review checklist:

- Fallback mode and token metadata remain visible in trace output.
- Exceptions from the LLM client do not escape normal Agent task execution.

### Task H4: Evaluation Gate

Purpose:

- Add machine-checkable pass/fail gate over evaluation metrics.

Required reads:

- `services/evaluation_service.py`
- `api/evaluation.py`
- `tests/test_agent_evaluation_and_tracing.py`

Allowed writes:

- `services/evaluation_gate.py`
- `services/evaluation_service.py`
- `api/evaluation.py`
- `tests/test_agent_evaluation_and_tracing.py`

Interface:

```python
@dataclass(frozen=True)
class EvaluationGateResult:
    passed: bool
    failures: list[str]
    metrics: dict[str, Any]


def evaluate_gate(summary: Mapping[str, Any]) -> EvaluationGateResult: ...
```

Default thresholds:

- `fallback_success_rate` must be `1.0` when present.
- `write_operation_violation_count` must be `0` when present.
- `json_parse_success_rate` must be at least `0.95` when present.
- Missing optional metrics do not fail the gate.

Verification:

```bash
pytest tests/test_agent_evaluation_and_tracing.py -q
pytest tests/test_agent_llm_and_mcp_adapter.py -q
```

Review checklist:

- Gate status is generated by deterministic code.
- Existing evaluation response fields remain compatible.

### Task H5: Trace Failure Export

Purpose:

- Convert failed online traces into eval-style records for regression datasets.

Required reads:

- `services/evaluation_service.py`
- `db/repositories.py`
- `domain/schemas.py`
- `tests/test_agent_evaluation_and_tracing.py`

Allowed writes:

- `services/evaluation_service.py`
- `tests/test_agent_evaluation_and_tracing.py`

Interface:

```python
def failed_trace_eval_records(self, *, limit: int = 50) -> list[dict[str, Any]]:
    ...
```

Record shape:

```json
{
  "case_id": "trace:<trace_id>",
  "task_type": "<task_type>",
  "payload": {},
  "expected": {
    "regression_source": "online_trace",
    "failure_reason": "<reason>"
  }
}
```

Verification:

```bash
pytest tests/test_agent_evaluation_and_tracing.py -q
```

Review checklist:

- Export does not include secrets, raw API keys, or large prompt bodies.
- Export is deterministic and bounded by `limit`.

### Task H6: Queue Metrics Extraction

Purpose:

- Reduce `QueueService` hub risk by extracting pure schedule metric helpers.

Required reads:

- `services/queue_service.py`
- `tests/test_queue_service.py`

Allowed writes:

- `services/schedule_metrics.py`
- `services/queue_service.py`
- `tests/test_queue_service.py`

Interface:

```python
def sla_status(finish_time: datetime, promised_finish_time: datetime | None) -> str: ...
def delay_minutes(finish_time: datetime, promised_finish_time: datetime | None) -> int: ...
def rate(numerator: int, denominator: int) -> float: ...
```

Verification:

```bash
pytest tests/test_queue_service.py -q
pytest tests/test_scheduling_optimization.py -q
```

Review checklist:

- Schedule metrics in API responses remain unchanged.
- No scheduling order or resource allocation behavior changes.

### Task H7: Durable Memory Cleanup Proposal

Purpose:

- Keep project-level Agent memory concise and specific.

Required reads:

- `AGENTS.md`
- `Harness.md`
- `README.md`

Allowed writes:

- `docs/harness_memory_cleanup.md`

Verification:

```bash
test -f docs/harness_memory_cleanup.md
```

Review checklist:

- This task creates a proposal only; it must not rewrite AGENTS.md directly.
- Proposal separates project facts from generic Harness theory.

## 10. Final Acceptance

The implementation is accepted only when:

- All completed task-specific verification commands pass.
- `pytest -q` passes or failures are documented as unrelated pre-existing
  failures with evidence.
- At least 6 unit, 3 integration, and 1 E2E Harness-related tests exist.
- No worker modified files outside its task allowlist.
- Every task has a code review result.
- Public Agent and Evaluation APIs remain backward compatible.
