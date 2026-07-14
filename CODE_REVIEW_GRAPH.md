# Code Review Graph — 电器产品质量检测多Agent仿真系统

> Generated: 2026-05-25 | Scope: full project | Last test run: 63 passed, 3 warnings

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Application (app.py)                 │
│  create_app() → wires all services → seeds data → registers routes  │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────┬───────┘
       │          │          │          │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────┐ ┌──▼─────┐
  │  API   │ │  Web   │ │ Agent  │ │  RAG   │ │  MCP   │ │  DB    │
  │ Layer  │ │ Routes │ │ Graph  │ │Retriever│ │ Client │ │ Layer  │
  └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘
      │          │          │          │          │          │
  ┌───▼──────────▼──────────▼──────────▼──────────▼──────────▼───┐
  │                      Services Layer                           │
  │  QueueService · SchedulerService · SimulationService ·       │
  │  NotificationService · MonitoringService · McpToolClient ·   │
  │  LLMClient · EvaluationService · SecurityService ·           │
  │  DatasetReplayService · ScheduleFormatter                     │
  └───────────────────────────────────────────────────────────────┘
```

### Module Dependency Map

| Module | Depends On | Exposes To |
|---|---|---|
| `app.py` | ALL services, ALL API routers, config, db | entry point |
| `agents/graph.py` | db.repositories, domain.schemas, rag.retriever, config.settings, 4 services | API agent.py |
| `api/agent.py` | agents/graph.py, dependencies.py | FastAPI router |
| `api/orders.py` | db.repositories, domain.schemas, services/scheduler_service | FastAPI router |
| `api/queue.py` | db.repositories, services/queue_service | FastAPI router |
| `api/scheduling.py` | services/scheduler_service | FastAPI router |
| `services/queue_service.py` | services/simulation_service, domain.schemas | graph.py, api/, coordinator |
| `services/scheduler_service.py` | db.repositories, services/queue_service, services/notification_service, services/schedule_formatter | graph.py, api/, app.py |
| `services/notification_service.py` | db.repositories, domain.schemas | graph.py, scheduler_service, api/ |
| `services/simulation_service.py` | domain.schemas (only) | queue_service, graph.py, app.py |
| `services/mcp_client.py` | services/tool_client.py, mcp SDK | graph.py, api/ |
| `services/llm_client.py` | config.settings, httpx | graph.py (exception_analyzer) |
| `rag/retriever.py` | rag/vector_store.py, config.settings | graph.py, api/ |
| `rag/vector_store.py` | numpy, (optional) faiss | retriever.py |
| `db/repositories.py` | db/models.py, domain.schemas | ALL services, API routers |
| `db/models.py` | domain.schemas | repositories.py |
| `domain/schemas.py` | pydantic (only) | EVERYTHING |

### Agent Graph Topology

```
START
  │
  ▼
orchestrator ──── routes by task_type ───→ 6 sub-agents
  │
  ├──→ order_manager ───────────────────→ END
  ├──→ project_identifier ─→ rag_retriever ─→ END
  ├──→ rag_retriever ───────────────────→ END
  ├──→ queue_scheduler ─→ equipment_monitor ─→ END
  ├──→ notification_agent ──────────────→ END
  └──→ exception_analyzer ──────────────→ END
```

**12 task types** routed to **6 sub-agents** (unknown types fall through to `exception_analyzer`).

---

## 2. Critical Findings

### 2.1 HIGH — CORS Wildcard with Credentials

**File:** [app.py:54-60](app.py#L54-L60)
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
**Risk:** `allow_origins=["*"]` combined with `allow_credentials=True` allows any origin to make authenticated requests. The browser will actually refuse this per the CORS spec (wildcard + credentials is invalid), so this is a silent misconfiguration — but if the middleware ever relaxes the check, it becomes a real vulnerability.
**Fix:** Either remove `allow_credentials=True` or enumerate allowed origins from settings.

---

### 2.2 HIGH — Path Traversal in Evaluation Service

**File:** [services/evaluation_service.py:235-239](services/evaluation_service.py#L235-L239)
```python
path = (self.base_dir / dataset_path).resolve()
if self.base_dir.resolve() not in path.parents and path != self.base_dir.resolve():
    raise ValueError("评测数据集路径必须位于项目目录内")
```
**Risk:** The traversal check exists but `self.base_dir` is resolved inside the check. If `dataset_path` is an absolute path (Pydantic's `min_length=1` doesn't prevent it), `self.base_dir / "/etc/passwd"` becomes `/etc/passwd`. The check `self.base_dir.resolve() not in path.parents` would correctly reject it since `/etc/passwd` won't have `base_dir` as a parent. However, the edge case where `dataset_path` equals `self.base_dir.resolve()` (e.g., `"/home/work/workproject2/project"`) would pass. Low real risk but the validation should use `os.path.commonpath` or similar for robustness.

---

### 2.3 MEDIUM — No Input Validation on Agent Run Request Payload

**File:** [agents/graph.py:74-86](agents/graph.py#L74-L86), [domain/schemas.py:293-295](domain/schemas.py#L293-L295)
```python
class AgentRunRequest(BaseModel):
    task_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
```
**Risk:** The `payload` is an untyped `dict`. Any key can be passed, and downstream agents consume keys like `query`, `certification_type`, `strategy`, `current_time`, `delta_minutes` with no schema validation. A malformed `certification_type` in `project_identifier` raises an unhandled `ValueError` that becomes an opaque graph error. Consider creating task-specific Pydantic models per `task_type`.

---

### 2.4 MEDIUM — Bare Exception Swallow in MCP Client

**File:** [services/mcp_client.py:82-86](services/mcp_client.py#L82-L86)
```python
def _call_or_fallback(self, tool_name, arguments, fallback_callable):
    try:
        return self._call_tool(tool_name, arguments)
    except Exception:
        return fallback_callable()
```
**Risk:** All exceptions (connection errors, timeouts, protocol errors) are silently swallowed with no logging. When the MCP server is failing, you have no visibility into why. Add a `logger.warning(exc)` at minimum.

---

### 2.5 MEDIUM — Scheduler Heartbeat Background Thread Safety

**File:** [services/scheduler_service.py:431-502](services/scheduler_service.py#L431-L502)
```python
class SchedulerHeartbeatService:
    def _run_background_loop(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.trigger()
            except Exception as exc:
                self._last_error = str(exc)
```
**Issues:**
1. `_last_error` is written from the background thread and read from API threads with no synchronization (it's a plain attribute, not protected by `_lock`).
2. `_last_run_at` and `_last_result` have the same race condition.
3. The `heartbeat_status()` method also reads these without the lock.

**Fix:** Use `self._lock` when reading/writing `_last_run_at`, `_last_result`, and `_last_error`, or use a `threading.Lock` per field.

---

### 2.6 MEDIUM — `_candidate_for_equipment` Loop Has Hardcoded 1000-Iteration Limit

**File:** [services/queue_service.py:296](services/queue_service.py#L296)
```python
for _ in range(1000):
    ...
    if employee_ids:
        return {...}
    next_release = self._next_employee_release(...)
    if next_release is None:
        return None
    current = max(next_release, start_time + timedelta(minutes=1))
```
**Risk:** If employees are consistently unavailable (e.g., all in exclusive mode), this loop runs 1000 times then returns `None`. The same pattern appears in `_schedule_support_step` (line 385). With many orders and many equipment instances, this becomes O(orders × equipment × 1000) which can be very slow. The loop should have a deterministic termination condition (e.g., stop if `next_release` exceeds a horizon).

---

### 2.7 MEDIUM — ScheduleOptimizer Runs Full Rebuild Per Strategy

**File:** [services/scheduler_service.py:36-58](services/scheduler_service.py#L36-L58)
```python
def analyze(self, orders, strategy=None):
    strategies = [strategy] if strategy else list(self.STRATEGIES)
    for item in strategies:
        schedule = self.queue_service.rebuild_schedule(orders, strategy=item)
```
**Risk:** When `strategy=None`, all 5 strategies are evaluated, each doing a full O(n²) schedule rebuild. With 500 orders this is 5 × 500² scheduling operations. The `queue_service.rebuild_schedule` also has side effects (`reset_runtime_state`, `last_schedule` mutation), so the last strategy's state is what persists on `queue_service.last_schedule`. This means `rebuild_schedule` is called 5 times but only the last call's side effects persist — the intermediate calls' `reset_runtime_state` calls corrupt each other's state.

**Fix:** The optimizer should not share the same `QueueService` instance. Either clone it or have `rebuild_schedule` accept a fresh state snapshot.

---

### 2.8 MEDIUM — Enum Comparison Bug in Queue Scheduler

**File:** [agents/graph.py:267-292](agents/graph.py#L267-L292)
```python
elif task_type == "rebuild_queue" and self.scheduling_coordinator:
    result = self._json_ready(
        self.scheduling_coordinator.rebuild(...)
    )
else:
    ...
    result = schedule if task_type == "rebuild_queue" else self.queue_service.snapshot()
```
**Issue:** When `task_type == "rebuild_queue"` and `self.scheduling_coordinator` exists, the first branch executes. When `self.scheduling_coordinator` is `None`, the else branch's ternary re-checks `task_type == "rebuild_queue"` — this works, but the first branch's result format differs from the else branch's result format. The first returns the coordinator's full response (run, schedule, analysis, notifications), the second returns just the raw schedule dict. API consumers get different shapes for the same task_type depending on coordinator availability.

---

### 2.9 LOW — `schedule_origin` Not Deterministic for Empty Orders

**File:** [services/queue_service.py:817-820](services/queue_service.py#L817-L820)
```python
def _schedule_origin(self, orders):
    if not orders:
        return self._next_work_start(datetime.now(self.DEFAULT_TZ))
```
**Issue:** When there are no orders, `schedule_origin` uses `datetime.now()`. This means the scheduling result is non-deterministic and changes on every call. In tests and evaluations, this can cause flaky behavior. Consider returning a fixed sentinel time or raising an error.

---

### 2.10 LOW — `_load_operations_constraints` Silently Returns `{}` for Missing File

**File:** [app.py:41-44](app.py#L41-L44)
```python
def _load_operations_constraints(path):
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}
```
**Issue:** If `operations_constraints.json` is missing, the system falls back to empty defaults from `SimulationService._build_operations_constraints({})`. No warning is logged, so a misconfigured path silently produces a working-but-wrong system.

---

## 3. Data Flow Graph

### 3.1 Order Lifecycle

```
POST /api/orders  →  OrderRepository.create()  →  DB
                        ↓
                  SchedulingEventService.create_order_event()
                        ↓
                  (heartbeat loop or manual trigger)
                        ↓
                  SchedulingCoordinatorService.rebuild()
                        ↓
                  ScheduleOptimizerService.analyze()
                        ↓ (5 strategies evaluated)
                  QueueService.rebuild_schedule()
                        ↓
                  ScheduleRepository.create_from_schedule()
                        ↓
                  NotificationService.generate_from_schedule()
                        ↓
                  SchedulingEventRepository.mark_done()
```

### 3.2 Agent Execution Path

```
POST /api/agent  →  AgentGraphRunner.run()
                        ↓
                  graph.invoke(initial_state)
                        ↓
                  orchestrator → route_map[task_type] → sub-agent
                        ↓
                  _instrument_node() wraps each agent with tracing
                        ↓
                  AgentTraceRepository.create_trace() (if evaluation)
                        ↓
                  Response: {result, visited_agents, handoffs, trace}
```

### 3.3 RAG Retrieval Path

```
KnowledgeRetriever.search(query)
  ├── store.load() → metadata.json + vectors.npy / index.faiss
  ├── (if empty) → reindex() → .txt/.md files → embed_documents() → build()
  ├── embed_query(query) → vector
  ├── faiss.search() or numpy.dot() → ranked results
  └── (if empty) → deterministic fallback response
```

---

## 4. Code Quality Assessment

### 4.1 Positive Patterns

- **Repository pattern** cleanly separates data access from business logic.
- **Pydantic schemas** provide strong input validation at API boundaries.
- **Enum types** (`OrderType`, `QueueStatus`, `CertificationType`, etc.) prevent string literal sprawl.
- **Deterministic fallback** in exception_analyzer ensures the graph always produces a result.
- **Heartbeat with lock** prevents concurrent scheduling runs.
- **Tracing instrumentation** wraps every agent node for observability.
- **Path traversal check** in evaluation service (though could be more robust).
- **Event fingerprinting** deduplicates scheduling events.
- **Multiple scheduling strategies** with scored selection provide flexibility.

### 4.2 Code Duplication

| Pattern | Occurrences | Files |
|---|---|---|
| `_enum_value(value)` | 7 | repositories.py, scheduler_service.py, queue_service.py |
| `_json_ready(value)` | 3 | graph.py, notification_service.py |
| `_parse_datetime(value)` | 6 | queue_service.py, repositories.py, notification_service.py, scheduler_service.py |
| `_ensure_tz(value)` | 3 | queue_service.py, scheduler_service.py |
| `_json_dump` / `_json_dict` / `_json_list` | 3 | repositories.py |

**Recommendation:** Extract `domain/serializers.py` or `domain/utils.py` with shared `_json_ready`, `_enum_value`, `_parse_datetime`, `_ensure_tz` functions.

### 4.3 Dead/Redundant Code

- **`services/simulation_service.py:307-359`** — `reserve_equipment_slot` and `required_batches` methods are only used by `McpToolClient.reserve_equipment_slot` which itself always delegates to `LocalSimulationToolClient`. The MCP stdio path for `reserve_equipment_slot` is never taken (it goes to fallback directly). These methods add complexity but limited value.
- **`services/mcp_client.py:58-59`** — `get_queue_snapshot` always uses fallback (never tries MCP).
- **`services/mcp_client.py:61-75`** — `reserve_equipment_slot` always uses fallback.

### 4.4 Inconsistent Patterns

| Area | Issue |
|---|---|
| Error responses | API returns `{"detail": "..."}` (FastAPI default) for validation errors but `{"error": "..."}` in notification_agent — inconsistent client contract |
| Session management | Some services open sessions inline (`with self.session_factory()`), others receive session as constructor arg. Repository classes always receive session, services mix both patterns |
| Timezone handling | `QueueService.DEFAULT_TZ` is UTC+8, `SchedulingEventService.DEFAULT_TZ` is UTC+8, but `SchedulingCoordinatorService._now()` defaults to UTC. This means heartbeat timestamps are UTC while queue scheduling is UTC+8 — potential time comparison bugs |

---

## 5. Security Review

| Finding | Severity | File |
|---|---|---|
| CORS wildcard + credentials | HIGH | app.py:54-60 |
| No auth middleware on API routes | MEDIUM | app.py (missing) |
| Unvalidated `AgentRunRequest.payload` | MEDIUM | domain/schemas.py:293 |
| Bare exception swallowing in MCP | MEDIUM | services/mcp_client.py:82 |
| `_json_dict` returns `[]` for empty input instead of `{}` | LOW | db/repositories.py:60-63 |
| `.env` file not gitignored (check .gitignore) | INFO | .env exists |
| API keys loaded from env with no masking in logs | INFO | config/settings.py |
| No rate limiting on API endpoints | INFO | app.py |

**Note on authentication:** The `UserModel` and `AuditLogModel` exist, and `PermissionService` / `AuditService` are initialized in `app.py`, but none of the API routers actually enforce authentication or permission checks. The permission system is seeded but unused. This is acceptable for a simulation prototype but should be addressed before production.

---

## 6. Performance Analysis

### 6.1 Scheduling Complexity

- `QueueService.rebuild_schedule()`: **O(n × m × k)** where n=orders, m=equipment instances per order, k=max iterations (1000).
- `ScheduleOptimizerService.analyze()` with all 5 strategies: **O(5 × n × m × k)**.
- With 500 orders, ~5 equipment types, and ~10 employees, this is roughly **5 × 500 × 5 × 1000 = 12.5M** inner loop iterations in the worst case.

### 6.2 Database

- `ScheduleRepository.create_from_schedule()` does **1 INSERT per step** (N+1 problem). For 500 orders with 3 steps each, that's ~2000 individual INSERTs.
- `SchedulingEventRepository._mark_many()` does **1 UPDATE per event** in a loop instead of using bulk UPDATE.
- `SchedulingEventRepository.count_pending()` fetches ALL pending events then counts in Python — should use `SELECT COUNT(*)`.

### 6.3 MCP Client

- `_call_tool_async` creates a new process (stdio server) for each tool call. No connection pooling or reuse.
- `anyio.run()` is called synchronously from a sync context, creating a new event loop each time.

### 6.4 RAG

- `FaissVectorStore.search()` returns all `top_k` results including zero-score matches (the `score > 0` filter helps but is post-ranking).
- `KnowledgeRetriever` calls `get_settings()` in constructor, which loads `.env` every time — redundant if multiple retrievers are created.

---

## 7. Test Coverage Analysis

| Module | Test Coverage | Notes |
|---|---|---|
| QueueService | test_queue_service.py, test_realism_improvements.py | Good: priority ordering, multi-step flows, personnel, consumables |
| SchedulerService | test_scheduling_events_and_optimizer.py | Good: event dedup, debounce, strategy scoring |
| Agent Graph | test_api_and_agents.py | Moderate: routes tested but no edge cases for exception paths |
| NotificationService | test_resource_constraints_and_notifications.py | Good: generation, types |
| RAG | test_rag_indexing.py, test_rag_and_tools.py | Good: index build/load/search |
| DB Migrations | test_db_migrations.py | Limited: only column migration |
| Evaluation Service | test_agent_evaluation_and_tracing.py | Good: offline eval, threshold status |
| MCP Client | test_agent_llm_and_mcp_adapter.py | Moderate: fallback behavior only, no stdio success path |
| SimulationService | (implicit via queue tests) | No direct unit tests |
| MonitoringService | test_execution_audit_monitoring.py | Moderate |
| DatasetReplay | test_dataset_replay.py | Good: start/step/tick/pause/resume/SSE |
| SecurityService | test_execution_audit_monitoring.py | Limited: audit logs only |
| Web routes | test_mcp_and_web.py | Minimal: page rendering only |
| ScheduleFormatter | (no dedicated test) | Tested indirectly |

**Gaps:**
- No tests for timezone edge cases (UTC vs UTC+8 inconsistencies)
- No tests for concurrent heartbeat scheduling (thread safety)
- No tests for `_candidate_for_equipment` loop termination
- No tests for `ScheduleOptimizerService` with all 5 strategies on large datasets
- No load/stress tests for 5000-order datasets

---

## 8. Recommendations (Priority Order)

### P0 — Fix Before Production

1. **Fix CORS configuration** — Remove `allow_credentials=True` or enumerate origins.
2. **Add authentication middleware** — The permission system exists but isn't enforced.
3. **Fix scheduler heartbeat thread safety** — Protect `_last_run_at`, `_last_result`, `_last_error` with locks.
4. **Fix optimizer state corruption** — `ScheduleOptimizerService.analyze()` shares and mutates `QueueService` state across strategy evaluations.

### P1 — Improve Soon

5. **Add logging to MCP client fallback** — `except Exception: pass` is dangerous.
6. **Fix timezone inconsistency** — Standardize on UTC internally, convert to UTC+8 only for display.
7. **Extract shared utilities** — Deduplicate `_enum_value`, `_json_ready`, `_parse_datetime`, `_ensure_tz`.
8. **Add bulk DB operations** — Use SQLAlchemy bulk insert/update for schedule persistence.
9. **Add input validation per task type** — Create Pydantic models for each agent's payload schema.
10. **Fix `_json_dict` returning `[]` for empty input** — Should return `{}`.

### P2 — Technical Debt

11. **Remove dead MCP paths** — `get_queue_snapshot` and `reserve_equipment_slot` always use fallback.
12. **Add deterministic `schedule_origin`** — Use a fixed time or raise for empty orders.
13. **Log missing `operations_constraints.json`** — Don't silently fall back to defaults.
14. **Add scheduling loop horizon** — Replace `range(1000)` with time-based termination.
15. **Count pending events with SQL** — Replace `len(list(...))` with `SELECT COUNT(*)`.
16. **Add connection reuse to MCP client** — Pool stdio sessions instead of creating per call.

---

## 9. Module Risk Matrix

```
                    High Change Freq     Low Change Freq
                 ┌────────────────────┬────────────────────┐
  High Complexity│ queue_service.py   │ db/models.py       │
                 │ scheduler_service  │ db/repositories.py │
                 │ agents/graph.py    │ rag/vector_store   │
                 ├────────────────────┼────────────────────┤
  Low Complexity │ api/*.py           │ config/settings.py │
                 │ web/routes.py      │ services/tool_client│
                 │                    │ domain/schemas.py  │
                 └────────────────────┴────────────────────┘
```

**High-risk zone** (top-left): Changes to `queue_service.py`, `scheduler_service.py`, or `agents/graph.py` have the highest blast radius. Always run the full test suite and check for regressions in scheduling behavior.

---

## 10. External Dependencies

| Dependency | Version | Risk |
|---|---|---|
| FastAPI | 0.115 | Low — stable, well-maintained |
| SQLAlchemy | 2.0+ | Low — mature ORM |
| LangGraph | 1.2+ | Medium — rapidly evolving API |
| LangChain | 0.3+ | Medium — large dependency tree |
| MCP SDK | 1.27+ | Medium — new protocol, API may change |
| FAISS-CPU | — | Low — stable, optional (numpy fallback) |
| Pydantic | 2.5+ | Low — stable |
| httpx | — | Low — stable |
| numpy | — | Low — stable |

---

*End of code review graph.*
