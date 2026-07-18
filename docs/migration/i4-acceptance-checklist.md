# Phase 5 / I4 acceptance checklist

This checklist records the bounded Phase 5 / I4 acceptance surface and the
minimal runtime recovery fix needed to close the live RabbitMQ health defect.

## Covered now

- Chroma backup archive creation and restore smoke drill against the Compose
  persistent volume.
- Public health aggregation through the real Go API process with injected
  PostgreSQL, RabbitMQ, Redis, partner write-back, and notification-channel
  probes.
- Sanitized health payload checks: component names and statuses only, without
  dependency URLs, stack traces, or panic output.
- Basic public-route security check: unauthenticated `GET /api/v1/session/me`
  returns `401`.
- Host-run OIDC discovery/JWKS stub under `tests/e2e/**` to keep I4 acceptance
  inside the allowed file boundary while bootstrapping the real Go API process.
- Authenticated public-route acceptance uses the same OIDC fixture boundary:
  the harness mints a scheduler/admin session cookie and drives real
  `schedule-previews` and `schedule-steps` routes without service-only bypasses.
- Dependency outage and recovery drills:
  - RabbitMQ outage => `degraded`
  - Redis outage => `degraded`
  - Partner write-back / notification channel outage => `degraded`
  - PostgreSQL outage => `unavailable`
- Concurrent approval race drill through the public route with a real signed
  OIDC session cookie:
  - exactly one `approve` succeeds
  - the losing request returns `409`
  - only one `schedule.writeback` outbox row is inserted
- Concurrent execution-start race drill through the public route with the same
  signed session cookie:
  - exactly one `schedule-steps/{step_id}/start` succeeds
  - the losing request returns `409`
  - the persisted notification set is deduplicated to the order creator plus
    the same-center scheduler recipients
- Bounded live performance evidence is captured for baseline health, preview
  creation, scheduler callback persistence, approval race, and step-start race.
  These timings are recorded as evidence only; they are not treated as product
  latency targets while the dataset remains incomplete.
- Scheduler guardrail acceptance now runs in the real `agent-learning` Python
  environment and proves:
  - production config rejects missing scheduler ingress/callback credentials
  - queue-size protection returns deterministic SLA fallback before solver work
  - configured solver time limit is forwarded into the solver entrypoint
  - timeout and execution errors map to the declared fallback reasons
  - callback submission preserves `preview_id`, `preview_version`, and the
    normalized candidate result hash

## Confirmed live findings so far

- The public preview-approval race drill passes with a real signed OIDC cookie:
  one concurrent approval returns `200`, the other returns `409`, the preview
  ends at `approved_pending_writeback`, and exactly one `schedule.writeback`
  outbox row is created.
- The authenticated step-start race also passes in the same Docker-backed run:
  one concurrent `schedule-steps/{step_id}/start` returns `200`, the other
  returns `409`, the step persists at `running` with version `2`, and the
  notification set is deduplicated to two recipients (`scheduler-e2e` as both
  creator and scheduler, plus `scheduler-peer` as the other center scheduler).
- The latest live run on July 17, 2026 confirms that a RabbitMQ outage now
  degrades `/api/v1/system/health` during the outage and returns the RabbitMQ
  component to `available` after the broker recovers, without restarting the
  host-run `api-go` process.
- The latest live run on July 17, 2026 captured bounded timings for the new
  authenticated flows without treating them as contractual latency targets:
  `health_baseline=29ms`, `preview_create=44ms`, `candidate_callback=25ms`,
  `approve_race=35ms`, and `step_start_race=29ms`.
- The scheduler guardrail drill passed on July 17, 2026 in the committed Conda
  `agent-learning` environment. It recorded deterministic oversized-input
  fallback with hash
  `sha256:b648ed174f7b4e5c3dbbd62ae5ae9df25c2a6f7524f4cdbd1a3f4d72f72a0e79`,
  confirmed `solver_time_limit_seconds=17` reached the solver entrypoint, and
  preserved callback `normalized_result_hash`
  `sha256:d2aadc679944139758460183126acd842e89bec086ad727a8be0a6d58964a914`.

## Execution

Run from the repository root in a controlled environment with Docker access:

```bash
bash tests/e2e/i4_health_and_recovery.sh
bash tests/e2e/i4_scheduler_guardrails.sh
```
