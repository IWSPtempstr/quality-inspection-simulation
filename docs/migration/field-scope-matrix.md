# Phase 5 / I2 field and scope matrix

This matrix defines what may enter the rebuilt platform during the one-time
Phase 5 / I2 import. Anything not listed here is excluded until a later
explicit contract amendment.

| Domain object | Import status | Required scope / fields | Exclusions and notes |
| --- | --- | --- | --- |
| Project catalog | import | stable project ID, code, name, applicability, center enablement, effective dates | Do not derive or rewrite required-project rules during import. |
| Equipment | import | `center_id`, equipment ID, name/code, eligibility attributes, capacity, active/deactivated state, maintenance/failure blackout windows when supplied | Reject rows without center scope or valid effective windows. |
| Employees | import | `center_id`, employee ID, role/eligibility attributes needed by scheduling, active/deactivated state | No passwords, sessions, or browser credentials. |
| Skills | import | employee ID, project/equipment eligibility links, effective dates | Reject orphan skills. |
| Shifts | import | employee ID, shift window, timezone-safe timestamps, version/effective fields where supplied | Crossing-midnight shifts must remain explicit, never normalized away. |
| Unavailability | import | employee ID or equipment ID according to target truth, reason/type, time window, center scope | Reject rows that overlap impossible identities or miss center ownership. |
| Orders | import | `center_id`, order ID, customer-facing structured fields defined by G4, promised time, state, creator, timestamps | No free-text order parsing or AI-derived fields. |
| Order projects | import | order ID, project ID, selected/retest state, result state where historically required | Reject orphan project rows. |
| Formal schedule versions | import | `center_id`, version number, base metadata, approved/write-back-complete versions only | Never import pending previews or candidate-only artifacts. |
| Schedule steps | import | formal schedule version, order ID, project/step identifiers, assigned resources, planned/actual times, `scheduled/running/completed/cancelled` state | Preserve running/frozen truth exactly; reject orphan steps. |
| Schedule previews | exclude | none | G6 preview lifecycle is transient and not part of I2 seed import. |
| Events | import | `center_id`, event ID, event type/source, lifecycle state, related entity/order references, timestamps, sanitized payload summary if required | Resource anomaly history may be visible, but Inbox retry state is excluded. |
| Notifications | import | `center_id`, notification ID, deterministic recipient, channel, body subject/body, delivery state, read state | Delivery retry history and broker envelopes stay excluded. |
| Audit logs | exclude by default | none | Only import if a later amendment explicitly requires historical audit retention. |
| Idempotency records | exclude | none | Runtime-only replay safety; do not seed. |
| Inbox events | exclude | none | G5 replay/backlog state is never bulk imported. |
| Outbox events | exclude | none | Recreated only by new deterministic writes after cutover. |
| Standard versions | import | version ID, document identity, effective dates, source URI, source hash, access scope | PostgreSQL remains authority. |
| Standard chunks | import | chunk ID, standard version ID, clause, page, language, source text, access scope, source hash | Do not import vector embeddings directly from legacy stores. |
| Approved exception cases | import | approved review record, redacted case body, center/access scope, equipment/project/event type, retention date | Only approved, unexpired, authorized cases are eligible. |
| Unapproved/revoked/expired cases | exclude | none | Must never become retrievable. |
| Redis memory / locks | exclude | none | Session memory, summaries, approval locks, and debounce keys are runtime-only. |
| RabbitMQ queues / DLQ | exclude | none | No queue-state replay during cutover. |
| Chroma/BM25 indexes | rebuild only | version names, counts, activation state produced from PostgreSQL truth | Keep prior versions for rollback window; do not source from direct legacy dump. |
