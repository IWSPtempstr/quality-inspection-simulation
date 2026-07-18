# End-to-end harnesses

This directory contains live environment checks that stay outside production
service code. Phase 5 / I3 currently provides:

- `i3_rabbitmq_and_writeback.sh`: starts the bounded Docker Compose stack,
  applies the existing SQL migrations, publishes a real RabbitMQ partner
  resource event, seeds an `approved_pending_writeback` preview, and verifies
  the resulting PostgreSQL and partner-stub state.
- `i4_health_and_recovery.sh`: starts the bounded dependency stack, verifies
  Chroma backup/restore smoke behavior, runs the real Go API process in
  host-worker mode, and checks sanitized health transitions across RabbitMQ,
  Redis, partner/notifier, and PostgreSQL outages.
- `i4_approval_race.sh`: starts the bounded dependency stack, uses a real
  OIDC-backed session cookie against the public approve route, and proves that
  only one concurrent preview approval succeeds while the losing request
  conflicts and no duplicate write-back intent is inserted.
- `i4_scheduler_guardrails.sh`: runs scheduler-side acceptance checks in
  process, proving production config validation, queue-size protection,
  solver-time-limit forwarding, deterministic fallback replay, and callback
  submission shape without changing runtime code.

The script is intended to run from the repository root:

```bash
bash tests/e2e/i3_rabbitmq_and_writeback.sh
bash tests/e2e/i4_health_and_recovery.sh
bash tests/e2e/i4_approval_race.sh
bash tests/e2e/i4_scheduler_guardrails.sh
```
