# Production Rebuild DEV_SPEC

> This document replaces the prior FastAPI/Jinja/LangGraph prototype spec and
> is the sole authority for the production rebuild. Any architectural change,
> package, endpoint, schema, directory, or allowed write not declared here
> requires a DEV_SPEC revision and human approval before implementation.

## 1. Product Decision

Build an internal, human-approved scheduling workbench for one electrical
product testing center. Employees enter complete structured orders and select
the required testing projects themselves. The system creates and evaluates a
candidate schedule; it never accepts free-text orders or automatically changes
the testing projects selected by the employee.

The primary scheduling objective is on-time delivery. The secondary objective
is minimizing changes to the approved schedule. Running steps and steps due to
start in the next 120 minutes are immutable during rescheduling. A candidate
schedule becomes formal only after a scheduler approves it and the partner
business system accepts the version-checked, idempotent write-back.

The production system must support the center's desensitized business corpus:

- approximately 1,200 historical orders;
- 28 equipment items and 16 employees with skills, capacities, shifts, and
  unavailable periods;
- more than 40 certification standard documents parsed into approximately 200
  versioned chunks;
- approximately 300 historic incidents for testing event processing only.

Historic incidents are not operational memory unless a human records the
diagnosis, action, outcome, owner, and review status in the new system.

## 2. Scope And Explicit Removals

### 2.1 Retained production capabilities

- Structured order creation, editing, cancellation, and retest creation.
- Resource registry for equipment, people, shifts, maintenance, and absence.
- CP-SAT primary scheduling and deterministic SLA fallback scheduling.
- Event-driven candidate rescheduling, change diff, human approval, audit, and
  version-checked/idempotent partner-system write-back.
- Step execution reporting and notifications.
- Versioned standard retrieval with clause/page citations and impact analysis.
- Evidence-bound event diagnosis, short session memory, compressed summaries,
  and reviewed long-term exception cases.

### 2.2 Removed from the production surface

- Natural-language order drafting and all `draft_order_from_text` routes.
- Testing-project recommendation and all `identify_projects` routes. Required
  project validation remains deterministic in the order form and Go API.
- Natural-language task routing, agent trace page, agent handoff visualization,
  and notification-copy agent.
- Strategy comparison, FIFO/EDD/SPT/bottleneck/hybrid algorithms, and every
  multi-strategy selector. Only CP-SAT and SLA fallback remain.
- LangGraph, LangChain, MCP, FAISS, in-memory simulation service, simulated
  clock, synthetic data replay, and their UI/API/routes.
- Dataset replay, simulation, and agent-evaluation APIs are not production
  modules. Historical data replay is permitted only as an offline scheduler
  evaluation command in Phase 3, with no public API or UI.

## 3. Mandatory Implementation Order

1. Phase 0: specifications, product design, and API contracts.
2. Phase 1: complete React frontend using mock contracts and fixed, desensitized
   fixture data only.
3. Frontend Gate: business workflow, accessibility, visual quality, and human
   acceptance.
4. Phase 2: Go business API and PostgreSQL persistence.
5. Phase 3: Python scheduler service.
6. Phase 4: Python AI service.
7. Phase 5: infrastructure, real-data migration, end-to-end acceptance, and
   old-system deletion.

Before the Frontend Gate is passed, implementation of `services/api-go`,
`services/scheduler-py`, and `services/ai-py` is prohibited. Phase 1 may use
only the OpenAPI schemas, MSW, and approved test fixtures.

## 4. Toolchain And Target Layout

### 4.1 Required runtimes

- Node.js 22.20.0 and npm 10.9.3.
- Go 1.26.3.
- Java 21 and OpenAPI Generator CLI 7.17.0, invoked through the committed
  `@openapitools/openapi-generator-cli` wrapper configuration. This is the
  only Go API contract generator; it is required because the public contract
  remains OpenAPI 3.1.
- Conda environment `agent-learning`, Python 3.12.13.
- PostgreSQL 16, RabbitMQ 4, Redis 7, Chroma, Docker Compose, and Nginx.

F1 must create `apps/web/scripts/with-toolchain.sh`, the only supported
frontend command wrapper. It loads NVM Node 22.20.0, adds Go 1.26.3 and Conda
`agent-learning` to `PATH`, verifies `node`, `npm`, `go`, and `conda`,
then executes its argument unchanged. It must fail clearly when any required
runtime is unavailable and must not silently select another Python interpreter.
All documented web checks use this wrapper rather than relying on a caller's
interactive shell or global PATH.

### 4.2 Packages

Web: React 19, TypeScript 5, Vite, React Router, TanStack Query/Table,
Zustand, React Hook Form, Zod, Radix UI primitives, Lucide React, Apache
ECharts, CSS Modules with OKLCH tokens, Vitest, React Testing Library, MSW,
Playwright, axe-core.

Go API: Gin, Gorm, PostgreSQL driver, goose, OIDC client, RabbitMQ client,
Redis client, OpenTelemetry, `log/slog`, and the pinned OpenAPI Generator
`go-gin-server` generator. Gorm owns persistence mapping and transactions.
Goose owns versioned SQL migrations. No Go scheduling package or algorithm
dependency is allowed.

Python scheduler: FastAPI, Pydantic, OR-Tools CP-SAT, RabbitMQ client, HTTPX,
Ruff, mypy, and pytest. Both scheduling algorithms live here.

Python AI: FastAPI, Pydantic, Chroma client, `rank-bm25`, Chinese tokenization,
`sentence-transformers` with local CPU `BAAI/bge-reranker-v2-m3`,
OpenAI-compatible LLM and embedding clients, Ruff, mypy, and pytest. Do not
add LangGraph, LangChain, MCP, FAISS, or another vector database.

### 4.3 Target layout

```text
apps/web/
  PRODUCT.md  DESIGN.md  package.json  package-lock.json
  src/{app,api,auth,components,features,mocks,styles}/
  tests/
services/
  api-go/
    cmd/{api,worker}/                 # process entry points only
    internal/
      api/                            # Gin handlers, middleware, request/response mapping
      clients/                        # PostgreSQL, Redis, RabbitMQ, OIDC, partner-system adapters
      conf/                           # typed config loading and validation
      core/                           # logging, tracing, lifecycle, request/correlation context
      entities/                       # business entities, commands, results, domain errors
      models/                         # Gorm persistence models only
      repositories/                   # PostgreSQL aggregate persistence and Inbox/Outbox access
      services/                       # use cases, transactions, RBAC/policy coordination
      workers/                        # RabbitMQ consumers and asynchronous application jobs
    migrations/                       # forward-only Goose SQL migrations
    scripts/                          # explicit operational/import tools, never application startup
    tests/
    conf/                             # versioned non-secret config examples/schema only
  scheduler-py/
    src/scheduler/
      api/                            # authenticated internal FastAPI endpoint
      clients/                        # RabbitMQ/HTTP callback adapters only
      conf/                           # typed settings and solver limits
      contracts/                      # immutable Go-issued snapshot/result schemas
      core/                           # logging, tracing, correlation context
      cp_sat/                         # CP-SAT model, constraints, objectives, result normalization
      entities/                       # scheduler-local immutable domain types
      services/                       # choose CP-SAT or SLA fallback; no persistence
      sla_fallback/                   # deterministic Python SLA algorithm only
      worker/                         # queued scheduling orchestration/callback retry
    scripts/                          # offline controlled-fixture evaluation tools only
    tests/
    conf/                             # versioned non-secret config examples/schema only
  ai-py/
    src/ai_service/
      agent/                          # ExceptionDiagnosisAgent and bounded tool policy only
      api/                            # authenticated internal FastAPI endpoints
      clients/                        # Go snapshot API, Chroma, Redis, LLM/embedding adapters
      conf/                           # typed settings, model and retrieval configuration
      core/                           # logging, tracing, correlation context, redaction
      entities/                       # structured requests, evidence, citations, memory/result types
      prompt/                         # prompt loading/rendering; no business decisions
      repositories/                   # Chroma/BM25/Redis access and read-only snapshot queries
      services/                       # retrieval, memory, diagnosis, explanation and draft use cases
      workers/                        # case-index Outbox consumer and reindex jobs
    prompts/                          # versioned static prompt resources loaded by `src/.../prompt`
    scripts/                          # explicit Chroma/BM25 build, verify, rollback utilities
    tests/
    conf/                             # versioned non-secret config examples/schema only
contracts/openapi/{public-v1.yaml,scheduler-internal.yaml,ai-internal.yaml}
deploy/{compose,nginx}/
docs/{product,migration,audits}/
DEV_SPEC.md
spec.md
```

The legacy `api/`, `agents/`, `web/`, `mcp_server/`, `rag/`, and prototype
`services/` remain read-only until Phase 5 I5. They must receive no new
features. Their source is evidence for migration, not a source of production
runtime dependencies.

### 4.4 Backend directory and dependency rules

This layout borrows the useful separation in the supplied example, but is
adapted to this project: Go/Gin/Gorm owns business writes; scheduler Python
owns algorithms; AI Python owns bounded assistance. There is no shared
application `agent/` package, no LangGraph graph directory, no MySQL/ES/Qdrant
client, and no Python ORM model layer.

- `api/` only parses/translates transport data, invokes a service, and maps
  typed errors. It must not call a repository/client directly or contain a
  transaction, solver, prompt, or business-policy decision.
- `services/` are the application-use-case boundary. Go services own
  transactions; Python services coordinate only their local explicit flow.
  They may depend on entities, repositories, and clients, but never on HTTP
  framework objects.
- `entities/` model business meaning and typed commands/results. They are not
  Gorm models, database rows, HTTP payload structs, or unvalidated LLM output.
- `models/` exists only in `api-go` and maps PostgreSQL tables through Gorm.
  `repositories/` converts models to entities and owns one persistence concern.
  Scheduler Python deliberately has neither directory because it has no direct
  business database access.
- `clients/` own connection/protocol concerns only. A Go client may call a
  Python service; an AI client may call Go's minimum read-only snapshot API;
  neither may embed business decisions or bypass service authorization.
- `agent/` exists only in `ai-py` and contains the explicitly bounded
  `ExceptionDiagnosisAgent`, tool allowlist, and tool-call budget. It may call
  AI services, never a browser, database driver, scheduler, or partner client.
- `prompt/` and `prompts/` exist only in `ai-py`. Prompt files are versioned
  resources; loading/rendering is separate from retrieval, tool execution, and
  output validation. Prompt text cannot grant a tool or mutation capability.
- `conf/` contains typed loading plus committed non-secret examples/schema.
  Secrets are injected at runtime and never committed. `core/` contains only
  cross-cutting technical utilities and must not import domain/application
  packages. `scripts/` are explicit operator commands, excluded from service
  startup and public APIs.
- `workers/` adapt queues/outbox jobs to application services. They do not
  duplicate handlers, scheduling algorithms, transactions, or approval logic.
  Scheduler `worker/` can orchestrate calls but CP-SAT/SLA rules remain in
  their dedicated directories.
- Runtime logs are emitted to stdout and centralized observability by default.
  A local `logs/` directory may be created by developer tooling but is ignored
  by Git and is never a source of business state, audit records, or memory.
- Services communicate only through declared OpenAPI/RabbitMQ contracts. No
  Python package imports Go code, no Go package imports Python code, and no
  service reads another service's private database/index directly.

### 4.5 OpenAPI 3.1 generation rules

`contracts/openapi/public-v1.yaml` remains OpenAPI 3.1. Do not downgrade its
JSON Schema syntax merely to satisfy a generator. `oapi-codegen` is prohibited
for this repository because it cannot safely generate the contract's OpenAPI
3.1 union/null schemas.

- The only approved Go public-server generator is OpenAPI Generator CLI
  `7.17.0`, using its stable `go-gin-server` generator. The npm wrapper version
  and generator version must be committed in `services/api-go` so a developer
  does not depend on a mutable user-home version selection. G1 owns exactly:
  `services/api-go/package.json` with the pinned wrapper dependency,
  `services/api-go/package-lock.json`, `services/api-go/openapitools.json` with
  `generator-cli.version = 7.17.0`, and
  `services/api-go/scripts/generate-openapi.sh` as the sole generation entry.
- Generation starts with the committed `public-v1.yaml`, performs OpenAPI
  Generator validation without `--skip-validate-spec`, and writes generated
  transport types and Gin server bindings under
  `services/api-go/internal/api/generated/`. The script must generate into a
  temporary sibling directory, format and compile it, then replace the prior
  generated directory atomically. Generated files are committed, never
  hand-edited, and regenerated only by that script.
- The generator invocation must use `--type-mappings null=Null`. The script
  writes the small generated-package support type `null.go` after every
  replacement; it marshals only as JSON `null` and rejects non-null input.
  This is an intentional typed OpenAPI 3.1 null representation, not an
  `interface{}` or `any` escape hatch.
- Handwritten `internal/api` code may only install middleware, connect a
  generated operation to its application service, and translate technical
  errors. It may not duplicate generated request/response structs or route
  parsing.
- OpenAPI Generator currently labels OpenAPI 3.1 support as beta. Every
  generator-version upgrade must run regeneration, `go test ./...`, `go vet
  ./...`, Spectral lint, and schema-focused contract tests for nullable values,
  `SchedulePreview`'s `oneOf`, `Problem` details, and the health response.
  A generated `any`/untyped replacement for one of those schemas is a failure,
  not an acceptable fallback.
- G1 mounts only the generated health operation plus the uncontracted process
  readiness endpoint `/readyz`. Future public operations remain unmounted until
  their corresponding G2-G8 task completes; generation itself must not expose
  placeholder business routes.

G1 verification must run, in order:

```bash
apps/web/scripts/with-toolchain.sh npm --prefix services/api-go ci
apps/web/scripts/with-toolchain.sh npm --prefix services/api-go exec -- openapi-generator-cli validate -i ../../contracts/openapi/public-v1.yaml
services/api-go/scripts/generate-openapi.sh
apps/web/scripts/with-toolchain.sh bash -c 'cd services/api-go && go test ./... && go vet ./...'
cd services/api-go && golangci-lint run
```

The generated transport contract tests must assert the JSON shape for
`Health`, nullable `DataQualityFinding.suggestion`, both branches of
`SchedulePreview.oneOf`, and RFC 9457 `Problem`. A generator warning is not a
failure by itself, but a warning may not be suppressed or converted into an
untyped value without an explicit DEV_SPEC revision and human approval.

## 5. Service Boundaries

### 5.1 React web

Owns display, client-side form validation, query cache, route permissions,
Gantt display, diff display, approval intent, and user-visible states. It does
not make final authorization decisions, calculate an SLA, calculate schedules,
control idempotency, or produce standards/event conclusions.

### 5.2 Go API

The only business write boundary. It owns OIDC/RBAC, PostgreSQL transactions,
orders, selected project validation, resources, events, schedule preview
persistence, approval, execution, notification, audit, RabbitMQ Inbox/Outbox,
Redis coordination, immutable scheduler snapshots, partner-system write-back,
and calls to the two Python services.

### 5.3 Python scheduler

Receives an immutable scheduling snapshot from Go and returns a candidate
schedule, metrics, and blockers. It must not access PostgreSQL, approve a
schedule, write to the partner system, accept public requests, or call an LLM.
`services/scheduler-py` is the sole owner of CP-SAT and the SLA fallback. Go
must not implement, duplicate, translate, or alter scheduling rules.

### 5.4 Python AI

Owns Chroma/BM25 standard retrieval, citation validation, standard-change
impact analysis, event diagnosis, session summary compression, and reviewed
long-term exception-case indexing. Its flow is explicit application-service
functions, not an agent graph. `ExceptionDiagnosisAgent` may call only the
read-only event, order, resource, schedule, standard-search, and
resolved-case-search tools. It has a five-tool-call limit and cannot write
orders, selected projects, resource state, schedules, approvals, or
partner-system data.

## 6. Data, Concurrency, And Integration Rules

### 6.1 PostgreSQL

PostgreSQL is the system of record. Core tables include `orders`,
`order_projects`, `equipment`, `employees`, `skills`, `shifts`,
`unavailability`, `standard_versions`, `schedule_versions`, `schedule_steps`,
`schedule_previews`, `schedule_preview_changes`, `events`, `notifications`,
`audit_logs`, `inbox_events`, `outbox_events`, `idempotency_records`,
`ai_sessions`, `ai_session_summaries`, and `resolved_exception_cases`.

G2 is deliberately limited to the PostgreSQL connection, Goose migration
runner, transaction unit, and the infrastructure tables `idempotency_records`,
`audit_logs`, and `outbox_events`. It must not create order, project,
equipment, employee, shift, or unavailability tables/models/repositories;
those belong to G4. It must not create `inbox_events` or RabbitMQ persistence;
that belongs to G5.

### 6.1.1 G4 confirmed business contracts

- The partner business system owns the global detection-project catalog. G4
  persists its versioned local projection; G5 later imports full snapshots and
  RabbitMQ increments. Projects apply to one or more of `CCC`, `CVC`, and
  `international`; center-project applicability decides selectability. Project
  and resource projections retain `source_id`, monotonic `source_version`,
  effective period, and soft-active state. A deactivated record remains
  historically visible but is excluded from new orders and allocations.
- A valid order enters `pending_schedule` directly. Order states are
  `pending_schedule`, `scheduled`, `in_progress`, `paused`, `completed`, and
  `cancelled`. There is no order-review state. Only scheduler/admin may pause
  an order without running steps; resume returns it to `pending_schedule`.
- Pending-schedule orders are fully editable. Scheduled orders only permit
  priority and promised-finish changes. Only pending-schedule, scheduled, and
  paused orders may be cancelled.
- A retest is a child order containing only requested source projects. A source
  project must be completed and `retest_required` or `failed`; running,
  pending, cancelled, and already-open-retest projects are rejected.
- All relevant records and queries are scoped by OIDC-derived `center_id`.
  Identical idempotency scope/key/request-hash requests return the stored first
  HTTP response; the same key with another hash returns RFC 9457 `409`. The
  idempotency record persists response status, content type, JSON response
  body, completion timestamp, and the scope
  `center_id + actor_id + operation + aggregate_id`.
- G4 creates only the projection schema and deterministic validation for the
  partner catalog/resources. Full-snapshot fetching, RabbitMQ consumption,
  stale-event rejection, retry queues, and Inbox persistence remain G5 work.

### 6.1.2 G5 confirmed messaging contracts

- A partner resource-event envelope requires `event_id`, `center_id`,
  `event_type`, `entity_type`, `entity_id`, `source_version`, `occurred_at`,
  and `payload`. G5 accepts only `equipment`, `employee`, `shift`, and
  `unavailability` entities with `upserted` or `deactivated` event types.
  Unknown, malformed, missing-center, and invalid-payload events are
  quarantined directly to the DLQ.
- `inbox_events.event_id` is globally unique. Source versions are monotonic
  per `center_id + entity_type + entity_id`; duplicate and stale events are
  durably recorded, acknowledged, and make no projection or rebuild change.
  Inbox records retain the envelope JSON, correlation ID, received time,
  status (`received`, `processed`, `stale`, `quarantined`), retry count,
  failure reason, and processed time before a projection update occurs.
- The resource projection update, Inbox completion, and optional Outbox insert
  are one PostgreSQL transaction. Repositories never commit independently.
- `partner.events` is a durable topic exchange; `api-go.g5.resource` binds
  `resource.#`. The worker uses manual acknowledgement and acknowledges only
  after successful processing or durable stale/quarantine classification.
  Transient failures route through durable 1-minute, 5-minute, and 30-minute
  retry queues, then `api-go.g5.resource.dlq` with original envelope and
  failure metadata.
- Unpublished Outbox rows are safely claimed and published unchanged through
  durable `internal.events` with routing key `schedule.rebuild.requested`.
  Publisher confirms are mandatory; `published_at` is set only after a
  confirmation. G5 publishes only immutable intent containing `center_id`,
  debounce-window start, triggering event IDs, and correlation ID. It never
  invokes the scheduler or creates a preview.
- Redis key `g5:resource-debounce:{center_id}` uses `SET NX` with a 45-second
  TTL. The first valid event in a window creates one rebuild intent; later
  valid events still update projections but create no second intent. If Redis
  is unavailable, the event remains durably `received`, receives no projection
  update or acknowledgement, and enters the retry chain. Retry delay exceeds
  the debounce TTL.
- G5 tests use PostgreSQL, RabbitMQ 4, and Redis 7 Testcontainers. They cover
  duplicate IDs, stale versions, center isolation, transactional rollback,
  debounce behavior, Outbox recovery/publisher confirms, manual ack, all retry
  queues, DLQ, and Redis outage retention. SQLite is prohibited.

### 6.1.3 G6 confirmed scheduling contracts

- G6 owns immutable Go snapshots, persisted candidate previews, human
  approval, and partner write-back persistence. It does not call the Python
  scheduler: until S4, an authenticated controlled callback writes fixture or
  internal candidate results.
- Creating a preview captures a center-scoped immutable snapshot of orders,
  selected projects, resources, current formal schedule, and frozen steps. A
  step is frozen when it is `running` or starts no later than
  `as_of + 120 minutes`. Persist `snapshot_id`, stable `input_hash`, `as_of`,
  base schedule version, resource snapshot version, immutable JSON, and
  preview version.
- `POST /internal/v1/schedule-previews/{preview_id}/candidate` requires
  the dedicated `X-Scheduler-Callback-Token` credential, sourced from
  `SCHEDULER_CALLBACK_SERVICE_TOKEN`; it must not reuse the Go AI/internal
  service token or the scheduler-ingress bearer token. Its exact body is
  `snapshot_id`, `input_hash`, `version`, `normalized_result_hash`, and
  `candidate`. `candidate` must satisfy the S1 `ScheduleCandidate` contract;
  `candidate.schedule.steps` is the sole source from which Go derives and
  persists normalized steps, so no separate `normalized_steps` input exists.
  Go recomputes the S1 canonical JSON SHA-256 over `candidate` and rejects a
  mismatching `normalized_result_hash` before changing state. It persists the
  hash with the candidate; callback identity is
  `preview_id + version + normalized_result_hash`. A repeat with that exact
  identity returns the persisted first success, while a different hash,
  snapshot, input hash, stale version, terminal state, or malformed request is
  a terminal 4xx rejection. A matching callback may only atomically transition
  `pending_candidate` to `pending_review`; it never approves, writes back, or
  creates a formal schedule version.
- Preview lifecycle is `pending_candidate -> pending_review -> rejected |
  approved_pending_writeback`; `approved_pending_writeback -> approved |
  conflicted | failed`. Only `approved` creates the next formal schedule
  version. Admin and scheduler roles may approve or reject. Every transition
  requires center isolation, If-Match, idempotency, append-only audit, and a
  transactionally consistent Outbox record.
- Redis provides a short approval lock. Redis outage rejects a new approval
  attempt with a degraded-service `503` and changes neither preview nor formal
  schedule state.
- The write-back worker sends conditional HTTP `PUT` to
  `/internal/v1/centers/{center_id}/schedule-versions/{target_version}` with
  `If-Match: <base_schedule_version>` and a stable idempotency key. Its payload
  contains center ID, preview ID, target version, and normalized schedule
  steps. Success atomically marks the preview approved, persists the formal
  version/steps, and audits. Timeout/5xx retains
  `approved_pending_writeback` for retry; partner 409/412 records a sanitized
  response summary, marks `conflicted`, and stops automatic retries.
- G6 tests use PostgreSQL, Redis, and an HTTP partner stub for snapshot hash
  determinism, frozen invariance, callback mismatch, center isolation,
  idempotent replay, concurrent single approval, reject terminality, Redis
  outage, write-back success, retry/recovery, and partner conflict. Callback
  coverage additionally proves the dedicated scheduler token, canonical-hash
  mismatch rollback, single `candidate.schedule.steps` derivation, and
  exact-identity replay versus mismatching-hash/version rejection. SQLite is
  prohibited.

### 6.1.4 G7 confirmed execution and operations contracts

- G7 owns formal step execution, system-created event lifecycle, deterministic
  notifications, health aggregation, and the bounded React API switch. It does
  not implement AI assistance, scheduler algorithms, Python scheduler calls,
  or G8 workflows.
- A successful G6 partner write-back expands the immutable approved formal
  schedule-version JSON into center-scoped `schedule_steps`; historical formal
  versions are never modified. Step lifecycle is `scheduled -> running ->
  completed` or `scheduled -> cancelled`. Starting records executor and actual
  start; completing records actual completion and deterministic project result.
  Start and complete require center isolation, executor role authorization,
  `If-Match`, `Idempotency-Key`, append-only audit, and transactional Outbox
  persistence. Running steps are immutable; G6 snapshot creation continues to
  freeze running steps and steps starting no later than `as_of + 120 minutes`.
- System-created events are center-scoped and transition `open -> acknowledged
  -> closed`, with direct `open -> closed` permitted. Execution, resource, and
  partner anomalies create `open` events. Only administrator or scheduler may
  acknowledge or close. Closure persists actor, timestamp, and disposition,
  does not request a schedule rebuild, and supplies only read-only facts to a
  later G8 case-candidate flow.
- Notifications are generated only by deterministic execution/event rules.
  Recipients are the affected order creator plus scheduler-role users in that
  center, de-duplicated. Supported channels are `in_app` and controlled
  `webhook_stub`; delivery lifecycle is `pending -> sent | failed` and uses the
  G5 durable retry/DLQ semantics. Read status is center-scoped and idempotent.
- Health reports PostgreSQL failure as `unavailable`; RabbitMQ, Redis, partner
  write-back, and notification-channel outages as `degraded`. It exposes only
  named component status, never URLs, credentials, partner bodies, or stack
  traces.
- React switches only G4-G7 flows to Go: orders/resources, previews,
  execution, events, notifications, and system health. G8 and knowledge
  surfaces remain MSW-backed. The UI waits for server confirmation and recovers
  from version conflicts; it must not optimistically mutate authoritative state.
- Every execution, event, and notification mutation couples aggregate state,
  audit, idempotency result, and Outbox insertion in one PostgreSQL transaction.
  G7 tests use PostgreSQL, RabbitMQ, Redis, and controlled channel/partner HTTP
  stubs for step version races, frozen invariance, event lifecycle, recipient
  isolation/deduplication, retry/DLQ, read idempotency, rollback, dependency
  health sanitization, and the bounded React contract/E2E switch. SQLite is
  prohibited. The delivery gate is `go test -count=1 ./...`, `go vet ./...`,
  fixed `golangci-lint v2.12.2`, and the affected frontend wrapper checks.
- G7 completion amendment: RabbitMQ declares a durable notification work queue,
  three durable notification retry queues delayed 1 minute, 5 minutes, and 30
  minutes, and a notification DLQ. Notification Outbox rows are published with
  broker confirmation and are marked published only after confirmation. A
  manual-ack notification worker persists `sent` only after `in_app` or the
  controlled `webhook_stub` adapter succeeds; a failure is durably recorded as
  `failed` before the message enters the retry chain and is never acknowledged
  early. Resource, execution, and partner anomalies create open events through
  the same transactional event/notification rule path.
- Health aggregation is injected at the API boundary and probes PostgreSQL,
  RabbitMQ, Redis, partner write-back, and notification channel independently.
  PostgreSQL failure returns overall `unavailable`; every other probe failure
  returns overall `degraded`. Responses retain only stable component names and
  statuses. G7 additionally requires PostgreSQL/RabbitMQ/Redis Testcontainers
  coverage for retry/DLQ, worker confirmation/failure, dependency health,
  anomaly event creation, recipient de-duplication, and transaction rollback.

G2 integration tests use the pinned Go module
`github.com/testcontainers/testcontainers-go v0.43.0` to start an isolated
`postgres:16-alpine` container. Tests run the forward-only Goose migrations,
use the container's per-test database URL, and terminate the container through
test cleanup. They must never read a developer, shared, or production database
URL. A missing Docker daemon is a clear integration-test failure, never a skip
or SQLite fallback.

All mutating public endpoints require `Idempotency-Key`. Business aggregates
use monotonic `version`; conflicting writes require `If-Match` and return RFC
9457 Problem Details with HTTP 409. Database unique constraints provide final
idempotency. Audit records are append-only and include actor, action, entity,
request/correlation IDs, before/after version, timestamp, and outcome.

### 6.2 RabbitMQ

Partner events use this envelope:

```json
{"event_id":"source-event-id","event_type":"equipment_failed","entity_type":"equipment","entity_id":"equipment-id","source_version":8,"occurred_at":"2026-07-13T08:00:00+08:00","payload":{}}
```

Use publisher confirms, manual acknowledgements, retry queues, DLQ, PostgreSQL
Inbox, transactional Outbox publication, source-version ordering checks, and
correlation IDs. A duplicate or stale event must not create an additional
reschedule. Event storms must be debounced before a reschedule request.

### 6.3 Redis

Redis is limited to: schedule-run coordination locks, short approval locks,
event debounce/deduplication, rate limiting, short-lived session cache, task
progress, and versioned standard-query cache. It must not store formal
business state, approved schedules, resource truth, approvals, long-term
memory, or durable RabbitMQ messages. If Redis is unavailable, Go rejects new
rescheduling and approval attempts with a degradated-service response; it must
not corrupt the last approved schedule.

### 6.4 Chroma, BM25, and memory

PostgreSQL is the authority for standard documents, chunks, exception cases,
versions, approvals, retention, and audit. Chroma is the sole vector database
and contains only rebuildable retrieval data. `standard_chunks_current` holds
the active standard chunk embeddings and metadata: `chunk_id`, standard ID and
version, effective dates, clause, page, language, source URI, access scope,
and source hash. `resolved_exception_cases_current` holds only approved,
redacted cases with `case_id`, center/access scope, equipment, project, event
type, review state, and retention date.

Each collection rebuild uses an immutable versioned name such as
`standard_chunks_v20260713`. PostgreSQL records the active, validated
collection version; activation is an atomic configuration change and old
collections remain through the configured rollback window before asynchronous
deletion. Chroma must have a persistent volume, health check, backup/restore
runbook, and version-aware rebuild lock.

BM25 is a separate versioned lexical index using the same `chunk_id` or
`case_id` as Chroma. A standard query applies access and standard-version
filters, retrieves Chroma Top 50 and BM25 Top 50, de-duplicates IDs, fuses
ranks with reciprocal-rank fusion (`k=60`), reranks the first 20 candidates
using local CPU `BAAI/bge-reranker-v2-m3`, and returns the first five with
clause, page, source text, and evidence state. Chroma and BM25 retrieval
failures must return a degraded no-evidence response; neither may affect
formal scheduling or approval consistency.

The short memory is per center, user, event, and session in Redis. Raw recent
turns have a 24-hour TTL; after eight turns or 6,000 tokens, the AI replaces
older turns with a structured summary whose TTL is seven days. Redis never
stores long-term cases. A long-memory candidate is stored in PostgreSQL first
and is indexed in Chroma through Outbox only after human review. Unreviewed,
revoked, expired, or unauthorized cases are never retrievable.

## 7. Public And Internal Contracts

All public API paths begin `/api/v1`, use `snake_case`, timezone-aware ISO
8601 timestamps, RFC 9457 errors, and the pagination shape `items`, `page`,
`page_size`, `total`.

```text
GET  /session/me
GET  /projects
GET|POST /orders
GET|PATCH|DELETE /orders/{id}
POST /orders/{id}/retests
POST /orders/{id}/{pause,resume}
GET  /resources/{equipment,employees,shifts,unavailability}
GET  /schedules/current
GET|POST /schedule-previews
GET  /schedule-previews/{id}
POST /schedule-previews/{id}/{approve,reject}
POST /schedule-previews/{id}/explanation
POST /schedule-previews/preflight
PATCH /schedule-steps/{id}/{start,complete}
GET  /events; GET /events/{id}; POST /events/{id}/diagnose; POST /events/{id}/close
POST /events/{id}/case-candidates; POST /exception-case-candidates/{id}/submit
POST /knowledge/query; POST /knowledge/impact-analysis
GET  /notifications; PATCH /notifications/{id}/read
POST /notification-drafts; POST /notification-drafts/{id}/send
GET  /audit-logs; POST /audit-logs/filter-suggestions; GET /system/health
```

The public OpenAPI contract fixes request/response schemas. Scheduler and AI
internal OpenAPI contracts separately define service authentication, immutable
input snapshots, versioning, timeout, error, and callback semantics. The AI
contract defines the six read-only diagnosis tools, their minimum snapshot
fields, the five-call limit, and a structured result containing affected
orders, frozen steps, SLA risks, affected resources, evidence citations,
resolved-case references, recommendations, evidence gaps, and confidence. The
Go API validates all Python outputs against these schemas before persistence.

`SchedulePreview.algorithm_used` may only be `cp_sat` or `sla_fallback`; it
must include solver status, fallback reason, base schedule version, resource
snapshot version, frozen/changed step counts, weighted/total delay, blockers,
changes, schedule, and preview version.

## 8. Scheduling Contract

### 8.1 CP-SAT primary algorithm

Hard constraints: ordered test steps; eligible equipment and capacity; employee
skill/role/shift/unavailability; equipment maintenance/failure; preprocessing
and transfer resources; consumables where supplied by source data; frozen
running steps; steps starting within 120 minutes; and no overlapping resource
allocation.

Lexicographic objectives:

1. minimize weighted SLA lateness (VIP, urgent, normal);
2. minimize number of late orders;
3. minimize total late minutes;
4. minimize time, equipment, and employee changes for non-frozen steps;
5. minimize equipment idle time.

Accept `OPTIMAL` and `FEASIBLE`. The snapshot includes a stable input hash and
as-of time. Solver limits and input-size protection thresholds are versioned
configuration. Result metrics must identify every unscheduled/blocked step.

### 8.2 Deterministic SLA fallback

Only trigger for CP-SAT `INFEASIBLE`, timeout without a feasible solution,
solver initialization/execution error, or input larger than the configured
protection threshold. Sort strictly by: overdue first; smallest remaining
slack; VIP then urgent then normal; earlier promise; earlier arrival; stable
order ID. Preserve frozen steps, assign the earliest valid equipment/employee
combination in sequence, enforce all hard constraints, and mark unschedulable
work blocked. Identical snapshots must produce byte-equivalent normalized
results. Never emit a constraint-violating best-effort schedule.

## 9. Product And Frontend Requirements

Roles: `admin`, `scheduler`, `operator`, and `viewer`. Permissions are enforced
by Go, while React hides or disables unavailable actions with a clear reason.

Routes: `/dashboard`, `/orders`, `/resources`, `/scheduling`, `/execution`,
`/events`, `/knowledge`, `/notifications`, `/admin/audit`, and `/admin/system`.

The visual register is a bright industrial workbench: graphite neutrals, cobalt
blue for primary actions, distinct semantic success/warning/danger/info colors,
and no initial dark mode. Use a restrained tokenized OKLCH palette; 24px page
titles, 14px body text, 13px tables, maximum 8px card radius, 150-200ms
stateful motion, and reduced-motion support. Do not use nested cards,
glassmorphism, gradient text, decorative grids, large shadows, or dashboard
marketing layouts. The design target is desktop 1280x800, 1440x900, and
1920x1080; at narrower widths the shell must remain usable but mobile is not a
release acceptance target.

Every page must include skeleton, empty, error, permission-denied, offline,
version-conflict, degraded-service, retry, and success-feedback states. Do not
optimistically update approval, execution, cancellation, or write-back state.

The scheduling workbench must visibly identify frozen steps, algorithm result,
fallback reason, schedule-version base, candidate diff, blockers, approval
state, and 409 conflict recovery. It also hosts an on-demand schedule
explanation panel for the selected preview, order, or step. The panel only
explains the persisted deterministic result and its evidence: hard constraints,
objective trade-offs, frozen-work effect, blocker, and fallback reason. It
cannot request a rebuild, alter a preview, or approve it.

The events page is the primary AI entry point. Rename the diagnosis action to
`获取诊断`; do not describe the user-facing action as "只读", even though its
implementation remains strictly read-only. Selecting the action opens an
event-scoped diagnosis drawer rather than a global chat page. The drawer shows
the current event context, bounded conversation, affected orders, frozen steps,
SLA risks, affected resources, cited standards, reviewed case references,
recommendations, evidence gaps, confidence, degraded state, and explicit
"insufficient evidence" outcome. It cannot close an event, create/rebuild a
schedule, modify an order/resource, persist a case, or send a notification.

The orders and resources pages must expose deterministic data-quality
prechecks in their existing form and detail workflows. Before a preview request,
the scheduling page aggregates those results in a preflight panel. Checks cover
missing or invalid required fields, project/standard version availability,
equipment applicability/capacity, personnel skill/shift availability,
unavailability overlap, promise-time validity, and stale source versions. A
data-quality assistant may explain a deterministic failed rule in plain language
and propose a correction, but it may not silently correct data, bypass a failed
check, or decide resource eligibility.

At event closure, the events page may offer an `异常案例候选` review drawer.
It presents a de-identified proposed summary, trigger, impact, disposition,
outcome, tags, source evidence, and retention period. The user must edit as
needed and explicitly submit it to the PostgreSQL review queue. This is a
candidate only: it is not long memory, does not enter Chroma, and is not
retrievable until an authorized reviewer approves it.

The audit page retains deterministic filters as its authoritative search. An
`审计辅助检索` panel translates a natural-language question into visible,
editable filter suggestions and returns only linked audit records within the
actor's center and permissions. It must label inferred filters, preserve the
original query, never invent audit evidence, and never write, redact, or alter
an audit record. The notifications page keeps deterministic event, recipient,
channel, and send authorization rules. `通知内容增强` is an optional draft
editor that may summarize or rewrite only the body; users preview/edit it and
the normal notification service performs the final send.

The knowledge page remains a standalone evidence workspace for standard Q&A
and impact analysis. Events, scheduling, orders, and case candidates may deep
link to a filtered knowledge result or citation; the page is not replaced by
the diagnosis conversation.

## 10. Legacy Risk Register And Anti-Regression Rules

The legacy Python monolith is a migration reference, not an implementation
template. Its detection-flow, resource, SLA, and execution rules must be
characterized with controlled fixtures and rule-level tests before replacement.
The currently incomplete desensitized dataset is not a source of delivery
metrics or acceptance thresholds. Its security, state, transaction, and
architectural defects must not be copied.

### 10.1 Prohibited legacy patterns

- No default administrator, header-trusted identity, client-supplied role, or
  unauthenticated fallback. Go validates OIDC tokens and derives actor ID,
  center scope, and roles only from verified claims.
- No session, trace, standard query, case, order, event, preview, or audit
  record may be read, reused, modified, or closed without actor and center
  scope checks. AI session keys and retrieval filters include center, actor,
  event, and session identity.
- No public or AI endpoint may expose arbitrary task dispatch. The
  `ExceptionDiagnosisAgent` has only its six declared read-only tools and may
  not create orders, rebuild schedules, send notifications, alter resources,
  or call a generic HTTP/SQL/tool executor.
- No in-memory singleton is authoritative for schedule, equipment, resource
  reservation, notification clock, event state, or session state. Every
  schedule calculation consumes an immutable Go-issued snapshot and returns a
  result without mutating shared application state.
- No repository method may independently commit an aggregate write. The Go
  application service owns one PostgreSQL transaction for the aggregate,
  audit record, idempotency record, and Outbox event. A failed transaction
  persists none of them.
- No process-local lock is accepted for rescheduling or approval. Redis locks
  coordinate work; PostgreSQL conditional updates, unique constraints, version
  checks, and Inbox/Outbox records provide the final correctness guarantee.
- No automatic schema creation, SQLite column patching, or production DDL at
  application startup. PostgreSQL schema changes are forward-only Goose
  migrations with rollback/runbook validation.
- No strategy comparison, mutable simulation service, simulation clock, data
  replay, legacy Agent graph, FAISS, Qdrant, MCP, or legacy API compatibility
  shim may enter the new runtime.

### 10.2 Required implementation shape

- Go handlers only decode/validate HTTP and map errors; application services
  own use cases and transaction boundaries; Gorm repositories persist one
  aggregate concern; RabbitMQ/partner clients are adapters; policy decisions
  remain in named domain/application functions.
- Scheduler Python accepts only the published snapshot contract. CP-SAT and
  SLA fallback share immutable input models and normalized output models but
  remain separate algorithms. Neither reads business storage nor has hidden
  process state.
- AI Python separates tool authorization/execution, retrieval, memory,
  prompting, structured-output validation, and case-index Outbox consumption.
  Chroma and Redis client failures become explicit degraded results, never
  hidden fallbacks or business writes.
- AI presentation follows workflow context instead of a generic chatbot. The
  diagnosis drawer is event-scoped; schedule explanation is result-scoped;
  data-quality explanation is rule-scoped; case summarization is closure-scoped;
  audit assistance is filter-scoped; notification enhancement is draft-scoped.
  Each feature states its evidence/degraded status and exposes only the action
  already authorized by the deterministic workflow.
- Deterministic rules own resource eligibility, validation failures, audit
  retrieval, event/notification routing, and all business mutations. AI may
  explain, summarize, retrieve cited evidence, or propose a non-binding draft;
  it cannot replace a rule result, initiate a sensitive write, or broaden its
  tool/data scope through user text.
- A task review rejects a new control-center file or function that mixes
  request parsing, authorization, transaction control, scheduling, persistence,
  LLM calls, response formatting, and background work. Small local duplication
  is preferable to a speculative shared abstraction; stable duplication is
  extracted only after it has at least two real consumers.

### 10.3 Mandatory regression and failure tests

- Characterization fixtures cover order routes, detection-step ordering,
  equipment/personnel eligibility, shift and unavailable windows, frozen
  execution steps, SLA weight, retest behavior, and blocked-resource reasons.
- Authentication tests prove anonymous and forged-role requests fail; tenant
  and actor isolation tests prove one user cannot read, reuse, close, or index
  another user's session or case.
- Transaction tests inject a failure at each order/event/audit/outbox and
  preview/approval/write-back boundary, then assert no partial aggregate state
  or duplicate external write exists.
- Concurrency tests run duplicate/out-of-order events and concurrent preview
  approvals/rebuilds across separate service processes. They assert exactly one
  formal approval/write-back, no duplicate event consumption, and no mutation
  of frozen steps.
- Scheduler regression tests compare CP-SAT and SLA output against approved
  controlled fixtures for hard-constraint violations, deterministic normalized
  output, and expected business statuses. They do not preserve legacy
  multi-strategy or simulation behavior as a requirement.

## 11. Spec-First Delivery Protocol

For every task: inspect Git baseline; use one fresh isolated worker; read only
task files and direct dependencies; modify only Allowed Writes; run declared
checks; repair at most three rounds; main agent reviews scope/boundaries;
updates `spec.md`; closes the worker; and creates one independent commit:
`rebuild: <task-id> <summary>`. Do not commit unrelated user changes.

`spec.md` status values are `pending`, `in_progress`, `blocked`, and `done`.
At the end of each major phase, add a cleanup audit listing temporary files,
their purpose, and keep/delete/review recommendation. Formal tests, production
business code, and approved operational diagnostics are never deleted merely
because they are small or new.

## 12. Tasks

### Phase 0: contracts and frontend foundation

| ID | Scope | Allowed writes | Required checks |
| --- | --- | --- | --- |
| D0.1 | Replace spec and ledger; record legacy removal inventory. | `DEV_SPEC.md`, `spec.md`, `docs/audits/**` | `test -f DEV_SPEC.md && test -f spec.md` |
| D0.2 | Product and design register: roles, workflows, page states, desktop acceptance. | `apps/web/PRODUCT.md`, `apps/web/DESIGN.md`, `docs/product/**` | Impeccable product-register review |
| D0.3 | Public, scheduler, and AI OpenAPI contracts; bootstrap the contract-lint toolchain wrapper required by its check. | `contracts/openapi/*.yaml`, `apps/web/scripts/with-toolchain.sh` | `apps/web/scripts/with-toolchain.sh npm --prefix apps/web exec -- spectral lint --ruleset contracts/openapi/.spectral.cjs contracts/openapi/*.yaml` |
| D0.4 | Extend public and AI-internal OpenAPI schemas for every G8/A8 mapping: schedule explanation, deterministic preflight explanation, case candidate/submit, audit-filter suggestion, and notification draft/send. Add the local Spectral OpenAPI ruleset configuration required for reproducible Node 22 linting. | `contracts/openapi/{public-v1.yaml,ai-internal.yaml,.spectral.cjs}`, `spec.md` | `apps/web/scripts/with-toolchain.sh npm --prefix apps/web exec -- spectral lint --ruleset contracts/openapi/.spectral.cjs contracts/openapi/*.yaml` |
| D0.5 | Retain OpenAPI 3.1 while completing the two `SchedulePreview.oneOf` boolean constant types needed for generated Go transport code. | `contracts/openapi/public-v1.yaml`, `DEV_SPEC.md`, `spec.md` | Spectral lint and generated transport contract checks |

### Phase 1: React only

| ID | Scope | Allowed writes |
| --- | --- | --- |
| F1 | Vite, TypeScript, npm lockfile/tooling, `with-toolchain.sh`, tokens, accessible primitives, application shell. | `apps/web/{package.json,package-lock.json,vite.config.ts,tsconfig*.json,scripts/with-toolchain.sh,src/app/**,src/styles/**,src/components/ui/**}` |
| F2 | Typed client from contract, MSW, auth role model, error mapping, router. | `apps/web/src/{api/**,mocks/**,auth/**,app/router.tsx}` |
| F3 | Dashboard and structured order list/create/edit/retest; no AI order/project features. | `apps/web/src/features/{dashboard/**,orders/**}`, `apps/web/src/mocks/**`, `apps/web/src/app/router.tsx`, `apps/web/src/**/*.test.*` |
| F4 | Equipment, employee, shift, and unavailability screens. | `apps/web/src/features/resources/**`, `apps/web/src/app/router.tsx`, `apps/web/src/**/*.test.*` |
| F5 | Gantt workbench, freeze indication, CP-SAT/SLA label, preview diff, approve/reject, and 409 recovery. | `apps/web/src/features/scheduling/**`, `apps/web/src/app/router.tsx`, `apps/web/src/**/*.test.*` |
| F6 | Execution state reporting and event view/diagnosis/close workflow. | `apps/web/src/features/{execution/**,events/**}`, `apps/web/src/app/router.tsx`, `apps/web/src/**/*.test.*` |
| F7 | Cited knowledge, notifications, audit and health management screens. | `apps/web/src/features/{knowledge/**,notifications/**,admin/**}`, `apps/web/src/app/router.tsx`, `apps/web/src/**/*.test.*` |
| F8 | E2E fixtures, screenshots, and gate report. | `apps/web/tests/**`, `docs/product/screenshots/**`, `docs/product/**`, `spec.md` |
| F10 | Contextual AI assistance presentation: rename event action to `获取诊断`; event-scoped diagnosis drawer; result-scoped scheduling explanation; deterministic data-quality prechecks and explanation; closure-scoped case candidate review; audit filter assistant; notification draft enhancement; contextual knowledge deep links. All behaviors use MSW fixtures and typed contracts only. | `apps/web/src/features/{orders/**,resources/**,scheduling/**,events/**,knowledge/**,notifications/**,admin/**}`, `apps/web/src/{api/**,mocks/**,app/router.tsx}`, `apps/web/tests/**`, `docs/product/**`, `spec.md` |

F10 required checks: component and role-permission tests for every entry point;
tests that diagnostic, explanation, precheck, candidate, audit, and draft
requests expose loading, evidence, degraded, insufficient-evidence, error, and
retry states as applicable; tests that no assistance UI exposes a direct
mutation; and Playwright flows for event diagnosis, preview explanation,
blocking preflight, candidate submission intent, editable audit filters, and
notification preview/send separation. Run `lint`, `typecheck`, `test`, `build`,
and relevant Playwright/axe checks through `with-toolchain.sh`.

Phase 1 first runs `apps/web/scripts/with-toolchain.sh npm --prefix apps/web
ci`. Task checks use `apps/web/scripts/with-toolchain.sh npm --prefix apps/web
run lint`, `run typecheck`, `test`, and `run build`; F5 onward additionally
runs relevant Playwright and axe tests through the same wrapper.

### Frontend Gate

Before Phase 2: all Phase 1 checks, including F10, pass; axe has zero
Critical/Serious issues; no overlap/overflow in the three desktop viewports;
all four roles have route
and action tests; MSW E2E covers order through preview, conflict, approval,
execution, incident, and cited knowledge journeys; Impeccable visual review
passes; and a human accepts the frontend. Record evidence in `spec.md`.

### Frontend Demo Acceptance Mode

Before the scheduler and administrator complete the human portion of the
Frontend Gate, the frontend provides a development-only manual acceptance mode.
It is a browser fixture surface, not a login or an authentication mechanism.

- It starts only with `VITE_DEMO_MODE=true` through the documented
  `npm run dev:demo` command and must never activate in a production build.
- It starts the existing MSW handlers in the browser and serves fixed,
  desensitized fixture data. It must not call a live API.
- It exposes a visible development-only role selector for `admin`,
  `scheduler`, `operator`, and `viewer`; switching roles updates only the
  in-memory frontend session. There is no employee-ID/password field, no
  credential storage, no token generation, and no authentication bypass.
- The selector is excluded from normal and production output. The application
  remains an OIDC/BFF-session client in Phase 2.
- The manual test guide must state the demo URL, roles, expected page access,
  data reset behavior, and the fact that its changes are never persisted.

| ID | Scope | Allowed writes | Required checks |
| --- | --- | --- | --- |
| F9 | Development-only browser MSW bootstrap, fixed role switching, and manual acceptance guide. | `apps/web/{package.json,package-lock.json,public/mockServiceWorker.js,src/main.tsx,src/app/**,src/mocks/**,src/**/*.test.*}`, `docs/product/**`, `spec.md` | `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`, `npm run dev:demo`, manual browser smoke test |

### Phase 2: Go, Gin, Gorm, PostgreSQL

| ID | Scope | Allowed writes |
| --- | --- | --- |
| G1 | Create the `api-go` directory skeleton defined in 4.3; committed OpenAPI Generator 7.17.0 `go-gin-server` wrapper/configuration and generated OpenAPI 3.1 transport boundary; mount only generated health plus `/readyz`; typed config, core lifecycle/observability, and separate API/worker entry points. No business repositories or use cases beyond health/readiness. | `services/api-go/**`, `spec.md` |
| G2 | PostgreSQL connection, Goose migration runner, transaction unit, and Gorm models/repositories only for `idempotency_records`, `audit_logs`, and `outbox_events`; Testcontainers Go `v0.43.0` with `postgres:16-alpine` integration coverage. Orders/projects/resources remain G4; Inbox/RabbitMQ persistence remains G5. | `services/api-go/**`, `DEV_SPEC.md`, `spec.md` |
| G3 | OIDC, four roles, audit, idempotency, version conflict middleware. | `services/api-go/**`, `spec.md` |
| G4 | Apply the confirmed G4 business contracts in 6.1.1: project catalog read, order/resource migrations and APIs, partial retest, pause/resume, center isolation, deterministic project validation, and persisted idempotency response replay. No RabbitMQ consumer, Inbox, scheduler, or approval implementation. | `services/api-go/**`, `contracts/openapi/public-v1.yaml`, `DEV_SPEC.md`, `spec.md` |
| G5 | Apply the confirmed G5 messaging contracts in 6.1.2: resource-event Inbox/projections, transactional Outbox, RabbitMQ retry/DLQ and publisher confirms, and Redis debounce/outage behavior. No scheduler invocation, preview, approval, project-catalog import, or partner write-back. | `services/api-go/**`, `DEV_SPEC.md`, `spec.md` |
| G6 | Apply the confirmed G6 scheduling contracts in 6.1.3: immutable snapshots, controlled candidate callback, persisted preview lifecycle, approval locks, and conditional partner HTTP write-back. No Python scheduler call, scheduling algorithm, execution reporting, notification, or G7 behavior. | `services/api-go/**`, `DEV_SPEC.md`, `spec.md` |
| G7 | Apply the confirmed G7 execution and operations contracts in 6.1.4: formal-step expansion/execution, event and deterministic notification lifecycle, health aggregation, and bounded React G4-G7 Go API switch. The existing main and demo Playwright configurations may be adjusted only to keep their already-separated live and fixture server responsibilities. No AI assistance, scheduler algorithm/call, or G8 behavior. | `services/api-go/**`, `apps/web/src/{api/**,mocks/**}`, `apps/web/tests/{playwright.config.ts,demo-playwright.config.ts}` only for that configuration separation, `contracts/openapi/public-v1.yaml` only when a missing execution/event schema prevents the contract, `DEV_SPEC.md`, `spec.md` |
| G8 | Data-quality preflight, AI-assistance facade endpoints, PostgreSQL case-review workflow, audit-filter validation, and notification draft/send boundary. Go validates actor/center scope and rule results; it never delegates a business mutation to AI. | `services/api-go/**`, `contracts/openapi/{public-v1.yaml,ai-internal.yaml}`, `apps/web/src/{api/**,mocks/**}`, `spec.md` |

#### G8/A8 interface mapping

React calls only the public Go endpoint. Go derives the actor, center, role,
and authoritative versions from the OIDC/BFF session, reads the smallest
immutable context, performs all deterministic validation, and calls the mapped
AI endpoint with service authentication. The browser never calls Python AI.

| F10 presentation and access | Go public endpoint | Python AI internal endpoint / capability | Result and hard boundary |
| --- | --- | --- | --- |
| Event `获取诊断` drawer; `admin`, `scheduler` | `POST /api/v1/events/{id}/diagnose` | `POST /internal/v1/diagnoses` / `ExceptionDiagnosisAgent` | Returns only the structured diagnosis, citations, reviewed-case IDs, memory status, degraded state, and evidence gaps. The agent is limited to the six declared read-only tools and five total calls. |
| Preview/order/step schedule explanation; `admin`, `scheduler`, `viewer` | `POST /api/v1/schedule-previews/{id}/explanation` | `POST /internal/v1/schedule-explanations` / `explain_schedule_result` | Go loads the persisted preview and its immutable snapshot references. The response explains the recorded solver result, diff, frozen work, blockers, and fallback status. It never invokes a solver, rebuilds, approves, or changes a schedule. |
| Order/resource edit and scheduling preflight; `admin`, `scheduler` | `POST /api/v1/schedule-previews/preflight` | `POST /internal/v1/data-quality-explanations` / `explain_failed_rules` | Go deterministically returns validation findings first. AI receives only failed rule codes and redacted field context, and may add an explanation/correction suggestion. The blocking result is identical when AI is unavailable. |
| Event-close case candidate and review submission; `admin`, `scheduler`, authorized reviewer | `POST /api/v1/events/{id}/case-candidates`; `POST /api/v1/exception-case-candidates/{id}/submit` | `POST /internal/v1/exception-case-candidates` / `extract_case_candidate` | Candidate generation is non-persistent. Only the explicit submit endpoint creates a PostgreSQL review-queue record with idempotency, actor audit, and retention metadata. Approval remains a separate reviewer workflow; no candidate is retrievable or indexed before approval. |
| Audit auxiliary search; `admin`, `scheduler` with audit-read permission | `POST /api/v1/audit-logs/filter-suggestions` | `POST /internal/v1/audit-filter-suggestions` / `suggest_audit_filters` | AI returns a structured proposed filter, explanation, and uncertainty. Go validates each field/operator/scope, displays it for editing, then runs the normal audited read query. It does not return records itself and never writes/redacts audit data. |
| Notification content enhancement and deterministic send; `admin`, `scheduler` with notification-send permission | `POST /api/v1/notification-drafts`; `POST /api/v1/notification-drafts/{id}/send` | `POST /internal/v1/notification-body-drafts` / `draft_notification_body` | AI drafts body text only. Go determines trigger, recipient, channel, template, and send eligibility. The draft must be previewed/edited; only the separate idempotent send endpoint creates delivery/outbox work. |

All G8 write endpoints require `Idempotency-Key`; candidate submission and draft
send also require `If-Match` when operating on an existing versioned record.
Read-like AI requests return a structured degraded/no-evidence result instead
of converting a retrieval/model outage into a business write. The exact request
and response schemas, Problem Details, permission scopes, and version fields
must be added to `public-v1.yaml` and `ai-internal.yaml` during G8/A8 before
the React MSW contract is switched to the real API.

Checks: `go test ./...`, `golangci-lint run`, contract tests, PostgreSQL
integration tests, and React contract E2E. Gorm must not use automatic schema
migration in production; Goose migrations are mandatory.

### Phase 3: Python scheduler

#### S1 confirmed scheduler foundation contract

S1 creates the Python scheduler's importable, solver-free foundation. It owns
only typed immutable contracts, typed non-secret configuration, normalized
candidate hashing, and package/test bootstrap. S1 does not expose an HTTP
route, consume RabbitMQ, call Go, call a partner system, persist a snapshot or
candidate, import OR-Tools, choose an algorithm, or create a schedule. Those
responsibilities remain respectively S4, S2, and S3.

The S1 contracts mirror `contracts/openapi/scheduler-internal.yaml` without
copying OpenAPI-generated code:

- `SchedulingSnapshot` accepts exactly `snapshot_id`, `input_hash`, `as_of`,
  `base_schedule_version`, `resource_snapshot_version`, `orders`, `resources`,
  and `frozen_steps`. It rejects unknown top-level fields, normalizes all
  datetimes to timezone-aware UTC, and preserves opaque order/resource/step
  payload fragments as JSON values rather than deciding their business meaning.
- `ScheduleCandidate` accepts `input_hash`, `algorithm_used`,
  `solver_status`, `fallback_used`, `fallback_reason`, `blocked_steps`,
  `schedule`, and `metrics`. `algorithm_used` is limited to `cp_sat` or
  `sla_fallback`; a non-fallback candidate requires `fallback_reason = null`,
  while a fallback candidate requires one of the four declared fallback
  reasons. S1 validates this shape but never selects either algorithm.
- `NormalizedCandidate` is the S1 result wrapper: it carries the validated
  `ScheduleCandidate` plus `normalized_result_hash`. The hash is
  `sha256:<hex>` over canonical UTF-8 JSON: recursively sorted object keys,
  stable list order, compact separators, and UTC RFC 3339 timestamps rendered
  with `Z`. Equivalent input therefore hashes identically; an input hash,
  schedule, blocker, metric, fallback, or timestamp change changes the result
  hash. The wrapper has no persistence behavior.
- Scheduler configuration is a frozen Pydantic settings model populated only
  from environment variables and `conf/` examples. It defines environment,
  service bearer token, callback base URL, queue names, solver time limit, and
  queue-size protection limit. Validation rejects missing production service
  token/callback configuration and non-positive limits. S1 does not open a
  connection or send a callback. Secrets are never committed or logged.
- S1 exposes pure functions only: parse/validate snapshot, parse/validate
  candidate, and normalize/hash a candidate. The later S4 adapter may call
  these functions after authenticating the service request and before its
  authenticated callback. The S4 callback must bind `snapshot_id`,
  `input_hash`, and the normalized-result hash; it may not trust browser input.

S1 creates only this layout:

```text
services/scheduler-py/
  pyproject.toml
  conf/config.example.env
  src/scheduler/
    __init__.py
    conf/{__init__.py,settings.py}
    contracts/{__init__.py,snapshot.py,candidate.py}
    core/{__init__.py,canonical_json.py}
    entities/{__init__.py,scheduling.py}
  tests/test_contracts.py
```

S1 must not create `api/`, `worker/`, `clients/`, `cp_sat/`,
`sla_fallback/`, `services/`, `scripts/`, database clients, queue clients, or
an application entry point. A dependency is allowed only when needed for this
contract foundation: Pydantic/Pydantic Settings, pytest, Ruff, and mypy.
FastAPI, OR-Tools, HTTPX, and RabbitMQ dependencies are introduced by their
own later tasks.

S1 delivery checks run from `services/scheduler-py` through the required
`agent-learning` Conda environment:

```bash
conda run -n agent-learning ruff check .
conda run -n agent-learning mypy src
conda run -n agent-learning pytest -q tests/test_contracts.py
```

Required S1 tests prove rejection of naive datetimes, unknown top-level
fields, invalid fallback combinations, and invalid settings; canonical hash
stability across dictionary key order; hash changes for semantic changes; and
the absence of solver, HTTP, broker, or database imports from S1 modules.
The existing OpenAPI Spectral lint remains required when
`scheduler-internal.yaml` changes. `spec.md` records S1 as done only after all
three Python checks pass.

#### S4 confirmed scheduler ingress and resilient callback contract

S4 connects the S1 immutable contracts and the S2/S3 pure scheduling functions
to the existing G6 preview boundary. It owns only the authenticated FastAPI
ingress, in-process worker lifecycle, callback client, and corresponding tests.
It does not create or modify snapshots, persist a scheduler-side database
record, consume RabbitMQ, invoke a partner, approve a preview, write a formal
schedule, or change CP-SAT/SLA algorithms.

- `POST /internal/v1/schedule` accepts only the service-authenticated
  `ScheduleSubmission` envelope from `scheduler-internal.yaml`:
  `preview_id`, `preview_version`, and immutable `snapshot`. Authentication is
  `Authorization: Bearer <SCHEDULER_SERVICE_BEARER_TOKEN>`. The endpoint
  validates the envelope and S1 snapshot before accepting a job, returns
  `202` with `{preview_id, preview_version, snapshot_id, status:"accepted"}`,
  and never exposes a candidate synchronously.
- The worker retains the accepted envelope only for its in-process job
  lifetime, selects CP-SAT first, and invokes the existing S3 fallback only
  for its explicitly permitted non-feasible triggers. It normalizes the chosen
  S1 candidate exactly once and uses its `normalized_result_hash` for every
  callback attempt. It must never accept a browser request, make a scheduling
  decision in Go, or create a G6 preview itself.
- The callback client sends `POST
  /internal/v1/schedule-previews/{preview_id}/candidate` to
  `SCHEDULER_CALLBACK_BASE_URL`, using
  `X-Scheduler-Callback-Token: <SCHEDULER_CALLBACK_SERVICE_TOKEN>`. Its body
  is the exact G6 callback schema: `snapshot_id`, `input_hash`,
  `version = preview_version`, `normalized_result_hash`, and `candidate`.
  Secrets, authorization values, raw response bodies, and candidate payloads
  are never logged.
- Only connection errors, timeouts, and HTTP 5xx are transient. The worker
  attempts the callback at most three times, immediately, after one second,
  and after five seconds. It stops immediately on every 4xx. After all
  transient attempts fail it records a sanitized local job failure while
  leaving the G6 preview `pending_candidate`; it must not acknowledge success,
  invent a preview state, or initiate approval/write-back. The G6 exact-identity
  replay rule makes a post-success transport-loss retry safe.
- S4 adds FastAPI/worker tests for invalid or missing Bearer authentication,
  strict envelope validation, preview/version/snapshot binding, correct
  callback authentication/body, all three transient attempts, immediate 4xx
  stop, callback replay, and sanitized final failure. It also adds fixed
  cross-language canonical-hash vectors shared with Go. The normal Phase 3
  Ruff, mypy, and pytest gate remains mandatory; callback-schema changes also
  require Spectral validation and the G6 Go test/vet/fixed-version lint gate.

| ID | Scope | Allowed writes |
| --- | --- | --- |
| S1 | Apply the confirmed scheduler foundation contract above: solver-free package bootstrap, immutable snapshot/candidate contracts, typed configuration, and normalized result hash. No FastAPI route, worker, callback, queue, solver, persistence, or scheduling decision. | `services/scheduler-py/{pyproject.toml,src/scheduler/{__init__.py,conf/**,contracts/**,core/**,entities/**},tests/test_contracts.py,conf/config.example.env}`, `spec.md` |
| S2 | CP-SAT constraints, lexicographic objective, metrics, blockers. | `services/scheduler-py/src/scheduler/cp_sat/**`, `services/scheduler-py/tests/**`, `spec.md` |
| S3 | Python-only deterministic SLA fallback. | `services/scheduler-py/src/scheduler/sla_fallback/**`, `services/scheduler-py/tests/**`, `spec.md` |
| S4 | Apply the confirmed scheduler ingress and resilient callback contract above. | `services/scheduler-py/{pyproject.toml,conf/config.example.env,src/scheduler/{conf/**,api/**,worker/**},tests/**}`, `services/api-go/{internal/api/g6.go,internal/services/scheduling.go,internal/entities/scheduling.go,internal/repositories/scheduling.go,internal/models/**,migrations/**,tests/**}`, `contracts/openapi/scheduler-internal.yaml`, `spec.md` |
| S5 | Controlled-fixture regression harness and reproducible rule-validation report, never replay UI/API. | `services/scheduler-py/src/scheduler/evaluation/**`, `services/scheduler-py/tests/evaluation/**`, `docs/product/scheduling-evaluation.md`, `spec.md` |

Checks in the conda environment: `ruff check .`, `mypy src`, and `pytest -q`.
Required tests include zero hard-constraint violations on controlled fixtures,
frozen step invariance, fallback determinism, fallback never used after
feasible CP-SAT, and fewer changes for equal SLA on equivalent fixtures. No
historical-SLA baseline, solve-rate, latency, or dataset-derived metric is an
acceptance gate until the data corpus and evaluation protocol are approved.

### Phase 4: Python AI

| ID | Scope | Allowed writes |
| --- | --- | --- |
| A1 | Create the AI-service directory skeleton defined in 4.3; internal API, typed config, core redaction/observability, LLM gateway, prompt loader, and structured output/citation validation. | `services/ai-py/**`, `contracts/openapi/ai-internal.yaml`, `spec.md` |
| A2 | Chroma standard/case collections, BM25 version indexes, metadata filters, activation and fallback search. | `services/ai-py/**`, `spec.md` |
| A3 | RRF hybrid retrieval, local Cross-Encoder reranking, cited standard Q&A and impact analysis. | `services/ai-py/**`, `spec.md` |
| A4 | Evidence-bounded `ExceptionDiagnosisAgent` and six read-only tools. | `services/ai-py/**`, `contracts/openapi/ai-internal.yaml`, `spec.md` |
| A5 | Redis short memory and structured session compression. | `services/ai-py/**`, `spec.md` |
| A6 | PostgreSQL review queue, Outbox, and approved exception-memory Chroma indexing. | `services/ai-py/**`, `spec.md` |
| A7 | Retrieval, citation, isolation, and outage evaluation gate. | `services/ai-py/**`, `spec.md` |
| A8 | Bounded assistance services: deterministic schedule-result explanation, failed-rule explanation, closure-case candidate extraction, audited filter suggestion, and notification-body draft generation. Each accepts only a minimal immutable context, emits structured evidence/degraded state, and has no mutation or generic tool capability. | `services/ai-py/**`, `contracts/openapi/ai-internal.yaml`, `spec.md` |

A8 owns the five non-diagnosis internal endpoints in the G8/A8 interface
mapping. Each request must include a Go-issued service identity, actor/center
scope, correlation ID, immutable context version/hash where applicable, and a
strict schema-specific response. It may not accept arbitrary tool names,
database queries, URLs, recipient lists, scheduling commands, or mutation
instructions from the browser or prompt text.

Checks in the conda environment: `ruff check .`, `mypy src`, `pytest -q`.
Acceptance: citations must be structurally present when evidence is returned;
no definite answer without evidence; no unreviewed incident in long memory;
cross-user memory leak 0; and Chroma, BM25, or Cross-Encoder outage degrades
safely. Retrieval hit rate, reranking precision, diagnosis accuracy, latency,
and other dataset-derived metrics are explicitly deferred until the corpus and
evaluation protocol are approved.

Additional assistance acceptance: the diagnosis service can issue no more than
the contractual five read-only calls and its UI presents an evidence-insufficient state;
schedule explanation is reproducible from a persisted preview and does not
invoke the scheduler; data-quality checks produce the same blocking result with
or without AI; an unapproved case candidate is absent from retrieval; audit
suggestions are visible/editable before deterministic filtering and return no
out-of-scope records; notification enhancement changes body text only and does
not send without the normal authorized action.

### Phase 5: delivery and cutover

| ID | Scope | Allowed writes |
| --- | --- | --- |
| I1 | Compose, Nginx, Chroma persistent volume/health/backup configuration, secrets/config and observability. | `deploy/**`, `spec.md` |
| I2 | One-time desensitized data import, reconciliation, and rollback runbook. | `docs/migration/**`, declared import files, `spec.md` |
| I3 | RabbitMQ partner-event and write-back stub end-to-end tests. | `tests/e2e/**`, `deploy/**`, `spec.md` |
| I4 | Performance, security, backup/restore, outage, and concurrency acceptance. | `tests/e2e/**`, `docs/migration/**`, `spec.md` |
| I5 | Delete legacy runtime only after cutover rollback window ends. | exact legacy files listed in a human-approved I5 DEV_SPEC amendment, `spec.md` |
| I6 | Final cleanup audit. | `docs/audits/**`, `spec.md` |

## 13. Production Risks That Must Be Tested

- Master-data drift: equipment capacity/skills and standards have effective
  dates; a scheduling snapshot must be reproducible after changes.
- Time semantics: use the center timezone, holiday calendars, DST-safe UTC
  storage, shift crossing midnight, and a single scheduler as-of time.
- Data quality: invalid project/equipment IDs, missing promised time, duplicate
  partner events, and stale source versions become quarantined events, not
  silent schedules.
- Approval races: one preview is approved once only; a stale base schedule or
  partner rejection moves it to conflict/failed state with a clear recovery.
- Solver performance: configured queue-size protection, time limits, metrics,
  and deterministic fallback prevent worker exhaustion. No solve-rate or
  latency target is accepted while the dataset remains incomplete.
- Standard governance: immutable document/version hashes, effective dates,
  reviewer workflow, citations, access control, and reindex rollback are
  required before AI answers affect operations.
- Security/privacy: OIDC token validation, least privilege, audit redaction,
  encryption/retention policy, no raw partner payloads in LLM prompts, and no
  sensitive data in traces/logs.
- Observability/operations: correlation IDs across web/API/queue/services,
  dashboards for backlog/solver/fallback/write-back/DLQ, backup restore drills,
  runbooks, alert ownership, and rate limits.

## 14. End-State Acceptance

The system demonstrates this boundary-preserving flow:

```text
partner event -> Go Inbox -> debounced scheduling request -> Python CP-SAT/SLA
-> persisted candidate preview -> React human approval -> Go version check
-> idempotent partner write-back -> audit/outbox notification
```

Redis, Chroma, BM25, and Cross-Encoder failures cannot compromise formal
business consistency. An unapproved preview cannot become the official
schedule. Concurrent approval has one success. Production contains no
LangGraph, LangChain, MCP, FAISS, Qdrant, simulation clock, data replay,
natural-language order/project entry, or multi-strategy scheduling entry.
