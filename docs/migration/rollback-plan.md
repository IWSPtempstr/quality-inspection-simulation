# Phase 5 / I2 rollback plan

## Trigger conditions

Trigger rollback when any of the following is true and cannot be safely
corrected before user enablement:

- imported row counts have unexplained mismatches;
- center isolation or relational integrity is broken;
- running/frozen schedule truth differs from the source snapshot;
- Chroma/BM25 rebuild or activation fails;
- approved/unapproved exception retrieval boundaries are violated;
- the application shows incorrect visible business state after import.

## Assets required before import starts

- PostgreSQL pre-import backup artifact with timestamp and checksum;
- Chroma pre-import archive with timestamp and checksum;
- manifest entry for the currently active Chroma/BM25 versions retained for the
  rollback window;
- named rollback approver and deadline.

## Rollback order

1. Stop user enablement and new business traffic.
2. Disable or pause workers that depend on imported business state.
3. Restore PostgreSQL from the pre-import backup.
4. Restore Chroma from the pre-import archive.
5. Reactivate the pre-cutover Chroma/BM25 versions recorded in the manifest.
6. Clear only runtime-generated Redis keys if they were created during the
   failed cutover.
7. Confirm RabbitMQ contains no cutover-generated business work that would
   replay into the restored state.
8. Re-run the reconciliation checklist against the restored baseline.
9. Record the final rollback result and evidence.

## Non-goals during rollback

- Do not replay historical partner events.
- Do not attempt selective row deletion instead of restoring the authoritative
  backup unless a human-approved incident plan explicitly overrides this runbook.
- Do not preserve failed import partial state for continued user traffic.

## Rollback completion criteria

Rollback is complete only when:

- PostgreSQL and Chroma are restored to the pre-import baseline;
- the previously active collection/index versions are confirmed active;
- users are blocked from the failed imported state;
- the evidence template records the rollback reason, timestamps, and approvers.
