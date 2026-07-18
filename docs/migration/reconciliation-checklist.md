# Phase 5 / I2 reconciliation checklist

Use this checklist during the actual cutover run. Every item needs an explicit
result and evidence reference.

## 1. Source integrity

- [ ] Every source export file path matches the manifest.
- [ ] Every file checksum matches the manifest.
- [ ] Every file row count matches the manifest.
- [ ] The source set contains only approved center IDs.
- [ ] The source set contains only desensitized data.

## 2. Target readiness

- [ ] PostgreSQL health is green.
- [ ] RabbitMQ health is green.
- [ ] Redis health is green.
- [ ] Chroma health is green.
- [ ] Edge/API/AI/scheduler routes are reachable.
- [ ] Pre-import PostgreSQL backup exists.
- [ ] Pre-import Chroma backup exists.

## 3. Entity count reconciliation

Record source count, target count, and explanation when they differ.

| Entity | Source count | Target count | Match? | Explanation / evidence |
| --- | --- | --- | --- | --- |
| Project catalog rows |  |  |  |  |
| Equipment rows |  |  |  |  |
| Employee rows |  |  |  |  |
| Skill rows |  |  |  |  |
| Shift rows |  |  |  |  |
| Unavailability rows |  |  |  |  |
| Order rows |  |  |  |  |
| Order-project rows |  |  |  |  |
| Formal schedule version rows |  |  |  |  |
| Schedule step rows |  |  |  |  |
| Event rows |  |  |  |  |
| Notification rows |  |  |  |  |
| Standard version rows |  |  |  |  |
| Standard chunk rows |  |  |  |  |
| Approved exception-case rows |  |  |  |  |

## 4. Integrity checks

- [ ] No orders exist without a valid center.
- [ ] No order projects exist without a valid order and project.
- [ ] No skills, shifts, or unavailability rows exist without a valid parent.
- [ ] No schedule steps exist without a valid formal schedule version.
- [ ] No notifications exist without a valid center-scoped recipient target.
- [ ] No approved exception case violates retention, approval, or access scope.

## 5. Business visibility checks

- [ ] Imported orders are visible in the correct center.
- [ ] Formal schedule versions are visible and immutable.
- [ ] Running/frozen steps match the source snapshot exactly.
- [ ] Events remain visible with expected open/acknowledged/closed state.
- [ ] Notification read state matches the source import set.

## 6. Retrieval checks

- [ ] Active standard collection version matches the manifest.
- [ ] Active approved-case collection version matches the manifest.
- [ ] Active BM25 versions match the manifest.
- [ ] Sample standard retrieval returns cited source metadata.
- [ ] Approved cases are retrievable only inside the correct center/access scope.
- [ ] Unapproved or revoked cases are not retrievable.

## 7. Final outcome

- [ ] All mismatches are explained and approved.
- [ ] Evidence template is complete.
- [ ] Business verifier signed.
- [ ] Platform verifier signed.
- [ ] Manifest final state set to `completed` or `rolled_back`.
