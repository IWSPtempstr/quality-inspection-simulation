# Product

## Register

product

## Platform

web

## Users

The primary user is the scheduler at an electrical-product testing center.
They work at a desktop workstation while reconciling orders, equipment,
personnel capacity, SLA commitments, and operational incidents. Operators use
execution and notification views to report completed work. Administrators use
resource, audit, and system-health views to govern the center.

## Roles

- `admin`: all capabilities, including resources, audit, and system health.
- `scheduler`: orders, schedule previews, approval, incident handling, and
  audit read access.
- `operator`: assigned step execution and notification read access.
- `viewer`: read-only orders, resources, schedules, and standards.

## Page Inventory

- `/dashboard`: current workload, SLA risks, active incidents, and capacity.
- `/orders`: structured orders, selected testing projects, edits, cancellation,
  and retests.
- `/resources`: equipment, employees, shifts, maintenance, and unavailable
  periods.
- `/scheduling`: current Gantt schedule, candidate previews, frozen steps,
  change diff, approval, and rejection.
- `/execution`: assigned step start and completion reporting.
- `/events`: event detail, cited diagnosis, candidate rescheduling entry, and
  human close-out.
- `/knowledge`: cited standard queries and impact analysis.
- `/notifications`: operational notification inbox.
- `/admin/audit` and `/admin/system`: audit trail, health, and service state.

## Shared States

Every page implements loading skeleton, empty, error, permission-denied,
network-offline, version-conflict, degraded-service, retry, and
server-confirmed success feedback. Approval, execution, cancellation, and
partner write-back never use optimistic updates.

## Product Purpose

The workbench turns complete, employee-entered orders and current resource
facts into an understandable candidate schedule. It helps a scheduler make a
human-approved decision, then track execution and incidents without losing the
evidence behind that decision. Success is an on-time, low-disruption schedule
whose constraints, risks, and changes are immediately legible.

## Positioning

Make every scheduling decision trustworthy before it becomes operational.

## Brand Personality

Calm, precise, reliable. The interface should feel like a well-maintained
industrial control desk: information-dense without being noisy, direct about
risk, and explicit about what is confirmed versus merely proposed.

## Anti-references

Do not make this a marketing-style SaaS dashboard. Avoid hero metrics,
decorative gradients, glass panels, large soft shadows, decorative charts, and
chat-first workflows. Do not present natural-language order drafting, testing
project recommendation, agent traces, strategy comparisons, or simulation
controls as product features.

## Design Principles

1. Show the decision evidence: SLA, frozen work, blockers, versions, and
   proposed changes are more important than decorative summaries.
2. Preserve operational continuity: destructive, approval, execution, and
   write-back actions require a clear server-confirmed state.
3. Optimize repeated work: dense, stable tables and predictable controls beat
   novelty for schedulers who return throughout the day.
4. Separate formal state from assistance: knowledge and diagnosis are cited,
   bounded support tools, never an alternative business-control surface.
5. Make degraded conditions actionable: offline, conflict, permission, and
   service-failure states explain what is safe to do next.

## Accessibility & Inclusion

Meet WCAG 2.2 AA. Every task is keyboard operable, focus is visible, semantic
structure is exposed to assistive technology, state is never communicated by
color alone, and motion respects `prefers-reduced-motion`.
