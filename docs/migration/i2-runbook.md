# Phase 5 / I2 one-time desensitized import runbook

## Purpose

This runbook defines the single approved Phase 5 / I2 path for importing the
existing desensitized business corpus into the rebuilt production stack. It is
for controlled cutover execution only. It does not authorize ad hoc reloads,
partial environment cloning, live dual-write, or any mutation outside the
explicit import window.

The import is intentionally conservative:

- PostgreSQL is the system of record for imported business facts.
- Chroma and BM25 receive only rebuildable retrieval data derived from the
  imported PostgreSQL state.
- Redis receives no imported data.
- RabbitMQ carries no replayed historical business traffic.
- The legacy runtime remains a reference source only until the rollback window
  closes under Phase 5 / I5.

## Inputs and companion files

Use this runbook together with:

- [import-manifest.template.yaml](./import-manifest.template.yaml)
- [field-scope-matrix.md](./field-scope-matrix.md)
- [reconciliation-checklist.md](./reconciliation-checklist.md)
- [rollback-plan.md](./rollback-plan.md)
- [evidence-template.md](./evidence-template.md)

The operator must create a filled import manifest for the actual cutover run
before changing any target environment.

## Source dataset assumptions

The approved source is the desensitized corpus described in `DEV_SPEC.md`:

- approximately 1,200 historical orders;
- 28 equipment items;
- 16 employees with skills, shifts, and unavailability;
- standards and approved reviewed exception memory suitable for bounded AI
  retrieval;
- existing current schedule facts required to preserve frozen-step semantics and
  approved formal versions.

The dataset is a cutover seed, not a complete historical replay stream.
Anything not explicitly listed as importable in the field/scope matrix is out
of scope for I2.

## Import scope summary

### Import in Phase 5 / I2

- project catalog and center enablement state required by G4 validation;
- orders and selected projects;
- equipment, employees, skills, shifts, and unavailability;
- current and historical formal schedule versions plus expanded schedule steps;
- system-created events that must remain visible after cutover;
- notification records that must remain visible for user read state;
- standard versions, chunk metadata, and approved redacted exception cases in
  PostgreSQL;
- Chroma/BM25 rebuild inputs derived from imported PostgreSQL standard and
  approved-case data.

### Never import in Phase 5 / I2

- Redis keys, short memory, summaries, locks, or debounce state;
- RabbitMQ queues, exchanges, retry backlogs, or DLQ contents;
- `idempotency_records`, `inbox_events`, or `outbox_events`;
- unapproved schedule previews or pending candidate artifacts;
- unapproved, revoked, expired, or unauthorized exception cases;
- raw partner tokens, browser sessions, passwords, OIDC cookies, or any secret;
- legacy debug logs, temporary scripts, or process-local caches.

## Roles and approvals

A cutover run requires these named owners:

- migration operator: executes the steps;
- business verifier: confirms counts and visible business state;
- platform verifier: confirms infrastructure health, backup artifacts, and
  rollback readiness.

No single operator may approve both execution and reconciliation sign-off
without a second reviewer recorded in the evidence template.

## Pre-cutover checks

Complete all checks before the first write:

1. Confirm `spec.md` shows Phase 5 / I2 as the active task and no later phase
   is marked complete.
2. Confirm the target stack is the I1 deployment skeleton and all required
   services are healthy: PostgreSQL, RabbitMQ, Redis, Chroma, edge Nginx,
   `api-go`, `ai-py`, and `scheduler-py`.
3. Confirm the target database is empty for business tables or matches the
   documented disposable rehearsal environment.
4. Create and record PostgreSQL and Chroma pre-import backups.
5. Freeze legacy writes for the defined cutover window.
6. Generate checksums for every source export file and write them into the
   import manifest.
7. Confirm the source export contains only desensitized data and no secrets.
8. Confirm the active center IDs to import and the business timezone for each
   center.
9. Confirm the rollback window end time and the person authorized to trigger a
   rollback decision.
10. Confirm Chroma/BM25 rebuild tools will run only from imported PostgreSQL
    source-of-truth data, never from direct legacy vector dumps.

If any pre-cutover check fails, stop and do not begin the import.

## Execution order

Run the import exactly once in this order.

### Step 1: record the immutable run header

Create a run ID and fill the manifest with:

- execution date and timezone;
- source export version;
- source file list with checksums;
- target environment name;
- cutover start time;
- approved rollback deadline.

### Step 2: load foundational reference data into PostgreSQL

Import only the approved foundational entities:

1. project catalog and center applicability/enablement;
2. equipment;
3. employees;
4. employee skills/role eligibility needed by scheduling;
5. shifts;
6. unavailability.

Rules:

- preserve source IDs when they are already business-stable;
- reject rows with missing `center_id` or impossible effective-time windows;
- reject duplicate natural keys instead of auto-merging;
- record row counts loaded and rejected by entity.

### Step 3: load order and schedule business state

Import:

1. orders;
2. order-project selections;
3. approved formal schedule versions;
4. expanded schedule steps for those formal versions;
5. currently visible system-created events;
6. notifications and read-state facts that must remain visible after cutover.

Rules:

- never import a preview as a formal version;
- preserve `running` steps exactly as source truth if they exist at cutover;
- preserve all step timestamps in timezone-aware ISO 8601 / UTC storage form;
- reject orphan steps, orphan projects, or orphan notifications;
- keep historical formal versions immutable.

### Step 4: load retrieval source-of-truth tables

Import into PostgreSQL only:

1. standard versions and chunk metadata/source text;
2. approved, redacted exception review records eligible for long memory.

Rules:

- do not import embeddings from the legacy system;
- do not import unreviewed or unauthorized cases;
- every imported case must carry its review state and retention boundary;
- every imported standard/case row must remain rebuildable into Chroma/BM25.

### Step 5: rebuild Chroma and BM25 from PostgreSQL truth

After PostgreSQL import completes successfully:

1. build a new immutable standards collection version;
2. build a new immutable approved-cases collection version;
3. build the matching BM25 versions;
4. validate counts and sample queries;
5. atomically activate the new collection/index versions;
6. record the rollback collection/index versions retained from before cutover.

Rules:

- activation must be atomic and versioned;
- old collections remain intact for the rollback window;
- failed rebuild or failed activation is an import failure and triggers the
  rollback decision path.

### Step 6: start messaging only after data truth is stable

After PostgreSQL import and retrieval activation succeed:

1. enable normal RabbitMQ partner-event consumption;
2. enable workers that depend on imported business state;
3. keep Redis empty except for runtime-generated keys.

No historical RabbitMQ payload may be bulk loaded as part of I2.

## Reconciliation gates

The cutover is not complete until all reconciliation gates pass.

### Gate A: row-count reconciliation

For each imported entity class, compare source manifest counts against target
counts. Every mismatch must be explained in writing as one of:

- expected exclusion by this runbook;
- source-row validation rejection;
- target deduplication caused by documented stable identity.

Unexplained mismatches fail the cutover.

### Gate B: relational integrity reconciliation

Confirm no target rows exist with broken references, including:

- order projects without orders;
- schedule steps without a formal schedule version;
- skills, shifts, or unavailability without an employee;
- events or notifications without their required center and business owner.

### Gate C: business-visibility reconciliation

Using the application surfaces and/or read-only queries, verify at minimum:

- imported orders are visible in the correct center;
- current formal schedule and steps are visible;
- frozen/running work appears unchanged from the source snapshot;
- events remain visible in expected lifecycle state;
- notification read state matches the import set.

### Gate D: retrieval reconciliation

Validate both standards and approved-case retrieval:

- imported standard version metadata matches the active retrieval version;
- approved cases are retrievable only within center/access scope;
- unapproved or revoked cases are not retrievable;
- degraded behavior is explicit if Chroma or BM25 validation fails.

### Gate E: audit and evidence completion

The manifest, reconciliation checklist, and evidence template must all be fully
filled and signed before the run is accepted.

## Failure handling

Treat these as hard-stop failures:

- source checksum mismatch;
- unexpected target preexisting business data;
- entity load rejection above the approved threshold in the manifest;
- broken foreign-key or center-scope integrity after load;
- Chroma/BM25 rebuild or activation failure;
- visible mismatch in running/frozen schedule facts;
- retrieval returning unapproved or cross-center cases.

When a hard-stop failure occurs:

1. stop later import steps immediately;
2. preserve logs, SQL counts, and screenshots as evidence;
3. decide either forward fix before enablement or full rollback;
4. do not open the system to users until one path is completed and signed off.

## Roll-forward constraints

A same-window roll-forward fix is allowed only when all of the following are
true:

- the target system is not yet opened to normal users;
- the defect is isolated and reversible;
- the fix does not require inventing a new import scope;
- both verifiers approve the plan in writing.

Otherwise trigger rollback.

## Cutover completion

The run closes only when:

- all reconciliation gates pass;
- rollback assets are confirmed and retained through the rollback window;
- the business verifier and platform verifier both sign the evidence template;
- the final manifest state is recorded as `completed`.
