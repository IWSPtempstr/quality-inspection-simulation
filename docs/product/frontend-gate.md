# Frontend Gate Evidence

## Automated Evidence

- Unit and integration tests: 57 tests passed with Vitest.
- Static checks: `npm run lint` and `npm run typecheck` passed.
- Production build: `npm run build` passed. Vite emitted a bundle-size advisory
  for the initial JavaScript bundle; this is a follow-up performance item, not
  a build failure.
- Browser gate: 6 Playwright tests passed using the required toolchain wrapper.
  The test exercises structured order creation, candidate-schedule conflict and
  approval, execution reporting, event diagnosis and human close-out, cited
  knowledge search, schedule explanation, deterministic preflight, case-review
  submission, editable audit filters, and notification draft/send separation.
- Accessibility: axe reported zero Critical or Serious violations on orders,
  scheduling, events, knowledge, and execution routes.
- Desktop viewport checks passed at 1280x800, 1440x900, and 1920x1080.
  Screenshots are retained in `docs/product/screenshots/`.
- Role coverage passed for `admin`, `scheduler`, `operator`, and `viewer`.
  Viewer order access is read-only; operational writes require the appropriate
  capability and server confirmation.
- OpenAPI contracts were re-linted after the gate fixes. They declare OIDC or
  service authentication, retest version preconditions, and the required
  scheduling fallback/blocker fields. D0.4 adds all F10 public/AI mappings.
  Spectral reports zero errors and 93 existing quality warnings for missing
  descriptions/tags/contact metadata across the original contract set.

## Remaining Human Gate

- A scheduler must accept the final visual hierarchy and day-to-day workflow.
- An administrator must confirm the role labels and permission presentation.
- Scheduler/admin must complete the F10 checks in `demo-acceptance.md` using
  the development-only role selector. Record approval or concrete findings in
  `spec.md`; only an approved gate permits G1.
- Phase 2 must enforce operator-to-step assignment on the Go API. The frontend
  only presents execution controls; it cannot be the authority for resource or
  step authorization.

## Phase 1 Cleanup Audit

| Path | Item | Purpose | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| `apps/web/src/mocks/**` | fixed fixtures | Deterministic Phase 1 API behavior | keep | Required before the Go API switch. |
| `apps/web/tests/frontend-gate.e2e.ts` | browser gate | Regression coverage for the frontend gate | keep | Formal acceptance test, not temporary scaffolding. |
| `apps/web/tests/artifacts/**` | Playwright failures/traces | Local diagnostic output | delete before commit | Generated test output; not source or acceptance evidence. |
| `test-results/**` | Playwright output | Local test output | delete before commit | Generated output only. |
| `docs/product/screenshots/**` | desktop visual evidence | Required Frontend Gate evidence | keep | Required by F8. |
| `.npm-cache/**` | npm cache | Local dependency cache | delete/ignore | Generated developer-machine cache. |
