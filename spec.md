# Rebuild Execution Ledger

## Baseline

- Status: `in_progress`
- Active phase: Phase 2
- Active task: G3
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
| G3 | pending | OIDC, RBAC, audit, idempotency, version-conflict checks | Next Phase 2 task. |
| G4-G8 | pending | Go checks and G8/A8 interface mapping defined in DEV_SPEC | Blocked by predecessor tasks. |
| S1-S5 | pending | Scheduler checks defined in DEV_SPEC | Blocked by Phase 2. |
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
