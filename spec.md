# Rebuild Execution Ledger

## Baseline

- Status: `in_progress`
- Active phase: Phase 3
- Active task: S4
- Git baseline observed: `main` is ahead of `origin/main` by one commit; user
  worktree changes include deletion of the prior `DEV_SPEC.md` and unrelated
  untracked documentation. These changes must not be reverted or committed by
  rebuild tasks.
- Runtime discovery: Node 22.20.0, npm 10.9.3, Go 1.26.3, and Conda are
  available from an interactive WSL shell but not the controlled execution
  PATH. F1 must add `apps/web/scripts/with-toolchain.sh` to load and verify
  NVM, Go, Conda, and npm before every web command. The frontend package
  manager is npm; `package-lock.json` and `npm ci` are mandatory.
- Architecture decision: Chroma is the sole vector database. PostgreSQL is the
  authority for standard and case facts; BM25 is the lexical index; Redis is
  only short-term session memory and summaries. FAISS, Qdrant, LangGraph,
  LangChain, and MCP are excluded from the target production runtime.
- Legacy-risk decision: the existing Python monolith is reference-only. Its
  business constraints require characterization tests; its default-admin
  identity, cross-user session access, process-local scheduling state,
  non-atomic commits, SQLite startup DDL, and multi-strategy simulation must
  not be replicated.
- Dataset decision: the current desensitized corpus is insufficient for
  dataset-derived acceptance metrics. Historical SLA comparisons, solve-rate,
  latency, retrieval hit rate, reranker precision, and diagnosis accuracy are
  deferred; controlled-fixture correctness and failure-mode tests remain
  mandatory.
- Task-order decision: D0.3 owns the minimal `with-toolchain.sh` bootstrap
  required to lint its OpenAPI contracts; F1 remains the owner of the complete
  npm application toolchain.
- AI-presentation decision: assistance is contextual rather than a generic
  chat feature. `/events` owns the event-scoped `获取诊断` drawer; scheduling
  owns deterministic-result explanation; orders/resources/scheduling own
  deterministic data-quality prechecks; event closure owns case candidates;
  audit owns editable filter suggestions; and notifications own body-draft
  enhancement. All business mutations remain deterministic and user-confirmed.
- G8/A8 contract decision: every F10 AI entry has a public Go facade and a
  mapped service-authenticated Python endpoint in `DEV_SPEC.md`. Candidate
  generation and notification drafting are non-persistent; case submission and
  notification send are separate idempotent, audited Go writes. React never
  calls Python AI directly.
- OpenAPI generation decision: retain OpenAPI 3.1. `oapi-codegen` is rejected
  because it cannot generate the contract's OpenAPI 3.1 union/null schemas.
  OpenAPI Generator CLI 7.17.0 with the stable `go-gin-server` generator is
  approved, pinned in the repository, and must generate committed transport
  code with explicit nullable/`oneOf` contract tests before G1 can close.
- OpenAPI 3.1 compatibility decision: the two `SchedulePreview.oneOf`
  `fallback_used` constants are explicitly typed as boolean without changing
  their JSON values or route surface. Generation maps JSON Schema `null` to a
  dedicated generated-package `Null` type; it must never emit untyped fallback
  representations for these schemas.
- G4 business-contract decision: the partner system owns a global project
  catalog with CCC/CVC/international applicability and center-specific enable
  state; both project/resource projections use a future full-snapshot plus
  RabbitMQ incremental import. Orders enter `pending_schedule` without review,
  use the confirmed six-state machine, and pause only through scheduler/admin
  when no step is running. A retest is a child order for completed failed or
  retest-required projects only. All facts are `center_id` scoped from OIDC;
  idempotent replay returns the persisted initial response while changed reuse
  returns RFC 9457 `409`. G4 owns schema/API/validation only; G5 owns import
  workers, stale-event handling, retries, and Inbox.
- G5 messaging-contract decision: resource events require center-scoped,
  version-ordered Inbox processing for equipment, employees, shifts, and
  unavailability. RabbitMQ uses manual acknowledgement, three durable retry
  queues and a DLQ; Redis provides only 45-second center debounce. Redis
  outage leaves an event durably received and retryable. Transactional Outbox
  publishes only `schedule.rebuild.requested` intent after broker confirms;
  G5 does not invoke the scheduler or create previews.
- G6 scheduling-contract decision: Go persists center-scoped immutable
  snapshots and fixture/internal candidates without calling Python until S4.
  Previews progress through review and approved-pending-writeback before a
  confirmed conditional partner HTTP PUT creates the formal schedule version.
  Approval uses Redis coordination and fails closed on Redis outage; partner
  timeout/5xx is retryable while 409/412 is a terminal preview conflict.
- G7 execution-and-operations decision: successful G6 write-back expands an
  immutable formal version into executable steps; execution, event, and
  notification writes are center-scoped, idempotent, audited, and Outbox
  transactional. Notification recipients are the affected order creator plus
  same-center scheduler-role users, de-duplicated. PostgreSQL outages are
  unavailable while supporting dependency outages are sanitized degraded
  component statuses. The React switch is limited to G4-G7 flows; G8/knowledge
  remains MSW-backed.

## Task Status

| Task | Status | Checks | Outcome |
| --- | --- | --- | --- |
| D0.1 | done | `test -f DEV_SPEC.md`, `test -f spec.md`, `git diff --check` | Production rebuild specification and ledger established; revised for Chroma-only retrieval/memory, legacy anti-regression, npm toolchain wrapper, and deferred dataset metrics. |
| D0.2 | done | Impeccable product-register manual review; `git diff --check` | `apps/web/PRODUCT.md` and `apps/web/DESIGN.md` define product register, desktop web platform, roles, routes, shared states, WCAG 2.2 AA, and visual rules. The Impeccable context script only searches root-level docs, so review used the task-owned files directly. |
| D0.3 | done | `apps/web/scripts/with-toolchain.sh npm --prefix apps/web exec -- spectral lint --ruleset contracts/openapi/.spectral.cjs contracts/openapi/*.yaml`; runtime wrapper checks | Public, scheduler, and AI contracts completed; idempotency, versions, CP-SAT/SLA-only algorithms, and read-only diagnosis-tool limits are explicit. |
| D0.4 | done | `apps/web/scripts/with-toolchain.sh npm --prefix apps/web exec -- spectral lint --ruleset contracts/openapi/.spectral.cjs contracts/openapi/*.yaml` | Public and AI-internal schemas now cover schedule explanation, deterministic preflight explanation, exception-case candidate/submission, audit-filter suggestion, and notification draft/send. Spectral completed with 0 errors; 93 pre-existing quality warnings across all three contracts are recorded for a dedicated contract-quality task. |
| D0.5 | done | Spectral lint; OpenAPI Generator contract output checks | Approved and completed 2026-07-14: both `SchedulePreview.oneOf` fallback constants now explicitly declare boolean. Spectral completed with 0 errors; generated Go contract types compile with typed `Null`, boolean fallback branches, nullable suggestion, and RFC 9457 Problem checks. |
| F1 | done | `npm ci`; `run lint`; `run typecheck`; `test`; `run build` through `with-toolchain.sh` | React/Vite/npm baseline, desktop shell, tokens, accessible primitives, and controlled toolchain wrapper completed. |
| F2 | done | `run lint`; `run typecheck`; `test`; `run build` through `with-toolchain.sh` | Typed API client, RFC 9457 errors, MSW fixtures, four-role capability model, session gate, route guards, and mock conflict tests completed. |
| F3 | done | `npm run lint`; `npm run typecheck`; `npm test`; `npm run build` through `with-toolchain.sh` | Dashboard and structured order list/create/edit/retest completed. Order and retest writes use server confirmation and `If-Match`; timestamp payloads are ISO 8601 with timezone; MSW persists confirmed fixture mutations; conflict and retry paths have tests. |
| F4 | done | `npm test -- src/features/resources/ResourcesPage.test.tsx`; `npm run lint`; `npm run typecheck`; `npm run build` through `with-toolchain.sh` | Read-only equipment, personnel, shift, and unavailability workbench completed with independent loading, empty, error, retry, filter, and degraded states. |
| F5 | done | `npm test`; `npm run lint`; `npm run typecheck`; `npm run build` through `with-toolchain.sh` | Scheduling workbench has Gantt, frozen-step display, CP-SAT/SLA labels, preview metrics/diff, server-confirmed approve/reject, and 409 refresh recovery. |
| F6 | done | `npm test`; `npm run lint`; `npm run typecheck`; `npm run build` through `with-toolchain.sh` | Execution reporting is server-confirmed with explicit degraded/offline/conflict recovery. Event diagnosis is evidence-backed and read-only; event close is human-confirmed with `If-Match` and conflict recovery. |
| F7 | done | `npm test`; `npm run lint`; `npm run typecheck`; `npm run build` through `with-toolchain.sh` | Cited knowledge and impact-analysis UI, server-confirmed notification reads, and read-only audit/system health screens completed. |
| F8 | done | `npm run test:e2e -- -c tests/playwright.config.ts`; `npm run lint`; `npm run typecheck`; `npm test`; `npm run build`; Spectral through `with-toolchain.sh` | Final evidence: 47 Vitest tests and four Playwright flows pass after contract/permission/layout fixes. Coverage includes role/action permissions, server-confirmed order-to-knowledge workflow, axe Critical/Serious checks, viewport integrity, and 1280x800/1440x900/1920x1080 screenshots. Evidence: `docs/product/frontend-gate.md`. |
| F9 | done | `npm run lint`; `npm run typecheck`; `npm test`; `npm run build`; `npm run test:e2e -- -c tests/demo-playwright.config.ts` through `with-toolchain.sh` | Development-only browser MSW fixture, visible in-memory role selector, manual acceptance guide, production exclusion tests, and browser smoke test completed. No credential, token, employee ID, or password flow was added. |
| F10 | done | `npm run lint`; `npm run typecheck`; `npm test`; `npm run build`; main and demo Playwright checks through `with-toolchain.sh` | Contextual assistance is MSW/contract-only: event-scoped `获取诊断` drawer; schedule explanation and deterministic preflight; order/resource prechecks; review-queue case candidate; editable audit filters; notification body draft and separate send. 57 Vitest tests and 6 main Playwright tests pass; axe has zero Critical/Serious findings on gate routes. |
| Frontend Gate | done | Accessibility, E2E, visual, human acceptance | Automated checks, screenshots, demo mode, and F10 evidence passed. Scheduler and administrator human acceptance was recorded on 2026-07-14 using `docs/product/demo-acceptance.md`; Phase 2 is unblocked. |
| G1 | done | `npm ci`; OpenAPI Generator 7.17.0 validation/generation; `go test ./...`; `go vet ./...`; fixed `golangci-lint v2.12.2 run`; production-dependency npm audit | Go 1.26 module, Gin/Gorm-declared skeleton, typed config, structured logging/correlation middleware, lifecycle, API/worker entry points, `/api/v1/system/health`, `/readyz`, generated OpenAPI 3.1 Gin transport types, and route-boundary tests completed. The generator uses a typed `Null` support type and explicit boolean `oneOf` constants; only health/readiness routes are mounted. All checks passed; production dependency audit found 0 vulnerabilities. |
| G2 | done | Goose migration; Testcontainers PostgreSQL 16 integration test; `go test ./...`; `go vet ./...`; fixed `golangci-lint v2.12.2 run` | PostgreSQL client, forward-only Goose runner, service-owned transaction unit, and Gorm models/repositories for `idempotency_records`, append-only `audit_logs`, and `outbox_events` completed. Testcontainers starts and cleans `postgres:16-alpine`; integration coverage verifies migration, rollback atomicity, successful three-table persistence, scoped idempotency uniqueness, and audit update/delete rejection. No order/resource/Inbox/RabbitMQ implementation was added. |
| G3 | done | Local OIDC discovery/JWKS verification; API middleware tests; PostgreSQL 16 Testcontainers integration test; `go test ./...`; `go vet ./...`; fixed `golangci-lint v2.12.2 run` | OIDC BFF-cookie verifier validates issuer, audience, signature, actor center and fixed roles. `GET /api/v1/session/me` is authenticated; health/readiness remain operational endpoints. Four-role capability checks, RFC 9457 authorization/precondition errors, `Idempotency-Key` and `If-Match` parsing, database-conflict-safe idempotency claiming, append-only audit service, and version comparison are ready for later write handlers. Tests verify roles, session rejection, header errors, real JWKS validation, duplicate/reused idempotency keys, audit correlation, and version conflict. No business aggregate route was mounted. |
| G4 | done | OpenAPI Generator validation; `git diff --check`; `go test -count=1 ./...`; `go vet ./...`; and `go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.12.2 run` passed in the Docker/listener-enabled controlled environment. | Implemented center-scoped project/order/resource reads and order writes, complete pending-order editing with scheduled-order field restrictions, partial-retest eligibility, no-running-step pause enforcement, resume/cancel, and transactionally persisted first-response idempotency replay. PostgreSQL integration coverage verifies byte-identical replay and rollback of a failed idempotency claim. Response bytes are retained in validated text rather than JSONB so PostgreSQL cannot reorder JSON object keys during replay. |
| G5 | done | PostgreSQL, RabbitMQ 4, and Redis 7 Testcontainers; `go test -count=1 ./...`; `go vet ./...`; and `go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.12.2 run` passed in the Docker/listener-enabled controlled environment. | Resource-event Inbox/projection import, transactional Outbox publication with publisher confirms and idle retry, three durable retry queues plus DLQ, Redis debounce/outage retention, manual acknowledgements, duplicate/stale/center isolation, and rollback/recovery coverage completed. G5 publishes only `schedule.rebuild.requested` intent and does not invoke the scheduler or create previews. |
| G6 | done | PostgreSQL and Redis Testcontainers plus HTTP partner stub; `go test -count=1 ./...`; `go vet ./...`; and `go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.12.2 run` passed in the Docker/listener-enabled controlled environment. | Immutable center snapshots preserve running and 120-minute frozen steps; controlled candidate callbacks bind preview/snapshot/hash/version; admins and schedulers approve/reject with Redis failure-closed locking, idempotent replay, audit, and Outbox. Partner HTTP 2xx alone formalizes a version, timeout/5xx retries, and 409/412 produces conflict without a formal version. No Python scheduler call was added. |
| G7 | done | `go test -count=1 ./...`; `go vet ./...`; fixed `golangci-lint v2.12.2`; PostgreSQL/RabbitMQ/Redis Testcontainers; frontend lint/typecheck/74 Vitest tests/build; main 5-flow and demo 1-flow Playwright checks | Formal-version step expansion/execution, event lifecycle, deterministic recipient de-duplication, RabbitMQ notification work/retry/DLQ path, transactional delivery state, injected sanitized health probes, and the bounded G4-G7 Go switch completed. PostgreSQL failure reports unavailable; RabbitMQ, Redis, partner, and notification failures report degraded. |
| G8 | done | `go test -count=1 ./...`; `go vet ./...`; fixed `golangci-lint v2.12.2`; PostgreSQL/RabbitMQ/Redis Testcontainers; OpenAPI Spectral (0 errors); frontend lint/typecheck/79 Vitest tests/build; main 5-flow and demo 1-flow Playwright checks | Go-only bounded A8 facade uses fixed-path Bearer service calls, deterministic degraded fallbacks, center-bound opaque candidate/draft references, deterministic preflight, transactional case-review and notification-send writes, and G8-only frontend API ownership. Knowledge and audit-list surfaces remain MSW-backed pending their later contracts. |
| S1 | done | `/root/anaconda3/bin/conda run --no-capture-output -n agent-learning ruff check .`; `mypy src`; `pytest -q tests/test_contracts.py` | Solver-free scheduler package foundation implements strict immutable snapshot/candidate contracts, frozen settings, canonical normalized result hashing, and later-phase import guards. No API, worker, queue, solver, persistence, or callback was added. |
| S2 | done | `/root/anaconda3/bin/conda run --no-capture-output -n agent-learning ruff check .`; `mypy src`; `pytest -q` (23 passed) | Pure CP-SAT scheduling projects controlled immutable snapshot fixtures into ordered resource assignments. It enforces ordered steps; equipment capacity/no-overlap; employee eligibility, shifts and unavailability; maintenance/failure blackouts; consumables; frozen work; and explicit preprocessing/transfer resource windows. Five sequential objectives minimize weighted lateness, late-order count, late minutes, formal-schedule changes, and makespan; every blocked step is reported. No fallback, API, worker, transport, persistence, or scheduler callback was added. |
| S3 | done | `/root/anaconda3/bin/conda run --no-capture-output -n agent-learning ruff check .`; `mypy src`; `pytest -q` (36 passed) | Pure Python deterministic SLA fallback accepts only explicit non-feasible CP-SAT failure triggers, preserves frozen capacity, applies stable overdue/slack/priority/promise/arrival/order ordering, enforces controlled hard constraints, reports blockers, and has no OR-Tools/API/worker/transport/persistence dependency. |
| S4 | done | `PYTHONPATH=src /root/anaconda3/bin/conda run --no-capture-output -n agent-learning ruff check .`; `PYTHONPATH=src /root/anaconda3/bin/conda run --no-capture-output -n agent-learning mypy src`; `PYTHONPATH=src /root/anaconda3/bin/conda run --no-capture-output -n agent-learning pytest -q`; `apps/web/scripts/with-toolchain.sh npm --prefix apps/web exec -- spectral lint --ruleset contracts/openapi/.spectral.cjs contracts/openapi/scheduler-internal.yaml` (0 errors, 5 warnings); `GOCACHE=/tmp/go-build-cache /usr/local/go/bin/go test ./... -count=1`; `GOCACHE=/tmp/go-build-cache /usr/local/go/bin/go vet ./...`; `GOCACHE=/tmp/go-build-cache GOMODCACHE=/tmp/go-mod-cache /usr/local/go/bin/go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.12.2 run` | Implemented the authenticated FastAPI scheduler ingress envelope, in-process CP-SAT-first worker, bounded callback retries with a dedicated callback token, sanitized local failure retention, and shared canonical candidate hashing. G6 now validates `normalized_result_hash`, derives persisted steps only from `candidate.schedule.steps`, accepts exact-identity replay, and persists callback hash identity. PostgreSQL migration `00007_s4_callback_contract.sql` adds the replay/hash column. Targeted and full Go tests passed in the Docker-enabled controlled environment; no RabbitMQ consumer, scheduler persistence, approval mutation, partner write-back initiation, or new solver behavior was added. |
| S5 | pending | Scheduler checks defined in DEV_SPEC | S5 is next; it remains blocked only by task order, not by S4. |
| A1-A8 | pending | AI checks and G8/A8 interface mapping defined in DEV_SPEC | Blocked by Phase 3. |
| I1-I6 | pending | Infrastructure checks defined in DEV_SPEC | Blocked by Phase 4. |

## Phase 0 Cleanup Audit

| Path | Item | Purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `DEV_SPEC.md` | specification | Production rebuild authority | keep | Required implementation contract. |
| `spec.md` | execution ledger | Task status and validation evidence | keep | Required spec-first record. |

## Phase 1 Cleanup Audit

| Path | Item | Purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `apps/web/src/mocks/**` | MSW fixtures and handlers | Contract-only frontend development and demo acceptance | keep until G7 | These fixtures are required while the React client has no Go API; G7 owns the controlled replacement path. |
| `apps/web/public/mockServiceWorker.js` | MSW browser worker | Development-only demo acceptance mode | keep until G7 | It supports the approved human-acceptance fixture runtime and is excluded from production behavior. |
| `apps/web/tests/**` | Vitest and Playwright regression suite | Frontend Gate behavior, accessibility, and visual coverage | keep | Formal regression coverage, not temporary test code. |
| `docs/product/screenshots/**` | Gate evidence screenshots | Desktop visual acceptance record | keep | Required evidence for the completed frontend phase. |
| `docs/product/demo-acceptance.md` | Manual acceptance guide | Reproducible scheduler/admin sign-off procedure | keep until G7 | It documents the current MSW-based acceptance workflow; revise when the real API integration replaces it. |

## Phase 2 G7 Cleanup Audit

| Path | Item | Purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `services/api-go/internal/services/notification_delivery.go` | controlled delivery adapter boundary | Persists deterministic in-app/webhook-stub delivery outcomes | keep | Formal G7 infrastructure boundary, not a temporary stub. |
| `services/api-go/tests/g7_*_integration_test.go` | Testcontainers regression coverage | Verifies execution, notification, retry, and DLQ contracts | keep | Required delivery evidence. |
| `apps/web/src/mocks/**` | fixture-only G8/demo support | Keeps G8 MSW-backed while G4-G7 uses Go | keep | Required bounded switch and demo acceptance surface. |

## Phase 2 G8 Cleanup Audit

| Path | Item | Purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `services/api-go/internal/clients/ai/client.go` | fixed-path service client | Calls only the six A8 contract endpoints with Bearer service identity | keep | Formal G8 boundary; it contains no AI implementation. |
| `services/api-go/internal/services/g8*.go` | facade and signed-reference logic | Builds minimal persisted context and protects candidate/draft references | keep | Required center-isolation and no-browser-trust boundary. |
| `services/api-go/tests/g8_assistance_integration_test.go` | PostgreSQL Testcontainers regression | Proves case/draft non-persistence, isolation, replay, and rollback | keep | Required delivery evidence. |
| `apps/web/src/mocks/**` | fixture-only knowledge/demo surface | Keeps knowledge and demo fixtures outside the bounded G8 Go switch | keep | Knowledge remains a later A2/A3 contract; demo requires fixed data. |

## Phase 3 S1 Cleanup Audit

| Path | Item | Purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `services/scheduler-py/.ruff_cache` | Ruff cache | Local static-analysis acceleration | delete | Ignored generated cache; recreated on demand. |
| `services/scheduler-py/.mypy_cache` | mypy cache | Local type-analysis acceleration | delete | Ignored generated cache; recreated on demand. |
| `services/scheduler-py/.pytest_cache` | pytest cache | Local test-run metadata | delete | Ignored generated cache; recreated on demand. |
| `services/scheduler-py/**/__pycache__` | Python bytecode | Import/test runtime cache | delete | Ignored generated cache; recreated on demand. |
| `services/scheduler-py/src/scheduler/**` | S1 contract foundation | Immutable validation, settings, and hashing modules | keep | Formal Phase 3 business-contract foundation. |
| `services/scheduler-py/tests/test_contracts.py` | S1 regression suite | Contract and forbidden-import coverage | keep | Required delivery evidence. |

## Phase 3 S2 Cleanup Audit

| Path | Item | Purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `services/scheduler-py/src/scheduler/cp_sat/solver.py` | CP-SAT implementation | Hard constraints, sequential objectives, blockers, and metrics | keep | Formal S2 production algorithm boundary. |
| `services/scheduler-py/tests/test_cp_sat.py` | controlled-fixture regression suite | Proves core hard constraints and objective behavior | keep | Required S2 delivery evidence. |
| `services/scheduler-py/**/__pycache__` and tool caches | validation outputs | Local interpreter and analysis caches | delete | Ignored and regenerated by the validation commands. |

## Phase 3 S3 Cleanup Audit

| Path | Item | Purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `services/scheduler-py/src/scheduler/sla_fallback/fallback.py` | deterministic fallback algorithm | Explicit failure-gated greedy candidate construction | keep | Formal S3 algorithm boundary. |
| `services/scheduler-py/tests/test_sla_fallback.py` | fallback regression suite | Trigger, determinism, frozen work, and hard-rule evidence | keep | Required S3 delivery evidence. |
| `services/scheduler-py/**/__pycache__` and tool caches | validation outputs | Local interpreter and analysis caches | delete | Ignored and regenerated by validation. |

## Phase 3 S4 Cleanup Audit

| Path | Item | Purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `services/scheduler-py/src/scheduler/api/**` | authenticated ingress boundary | Accepts immutable preview-bound submissions only from the Go service | keep | Formal S4 transport boundary with no persistence or browser entry. |
| `services/scheduler-py/src/scheduler/worker/**` | in-process callback orchestration | Chooses CP-SAT/fallback, normalizes results once, and retries the callback with sanitized failure retention | keep | Formal S4 execution boundary; it is explicitly limited to in-process lifecycle and callback delivery. |
| `services/scheduler-py/tests/test_s4_api_and_worker.py` | S4 regression suite | Verifies Bearer auth, envelope validation, callback body/auth, retries, 4xx stop, and hash vector stability | keep | Required S4 delivery evidence. |
| `services/api-go/migrations/00007_s4_callback_contract.sql` | callback replay/hash migration | Persists the candidate hash needed for replay-safe G6 callback identity | keep | Formal S4/G6 persistence adjustment required by the amended contract. |
| `services/api-go/internal/services/scheduling_test.go` | cross-language hash vector test | Keeps Go canonical hashing aligned with the Python scheduler contract | keep | Required guard against cross-language replay/hash drift. |
| `services/scheduler-py/**/__pycache__` and tool caches | validation outputs | Local interpreter and analysis caches | delete | Ignored generated artifacts, not production state. |
