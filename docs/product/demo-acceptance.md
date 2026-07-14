# Frontend Demo Acceptance

## Start

From `apps/web`, run:

```bash
./scripts/with-toolchain.sh npm run dev:demo
```

Open the local URL reported by Vite, normally `http://127.0.0.1:5174/`. This
command enables a development-only MSW browser fixture. The normal `npm run dev`
command, production build, and production preview do not enable the fixture or
the role selector.

## Role Checks

Use the visible `演示角色` selector in the application header. It has four fixed
roles and changes only the current browser tab's in-memory session.

| Role | Expected accessible areas |
| --- | --- |
| `admin` | All pages, including execution, audit, and system status. |
| `scheduler` | Dashboard, orders, resources, scheduling, events, knowledge, notifications, and audit; execution and system status are unavailable. |
| `operator` | Execution and notifications only. |
| `viewer` | Dashboard, orders, resources, scheduling, events, knowledge, and notifications; no write or administration pages. |

For each role, verify that navigation matches the table. To inspect the existing
permission-denied state, open a page as a role that can access it, then switch
to a role that cannot while remaining in the same tab. Exercise the relevant
pages against the fixed, desensitized fixture data.

## F10 Assistance Checks

Use the `scheduler` role for the following workflow. Every result is an MSW
fixture and must remain non-persistent after reload.

1. On `/scheduling`, select `查看排程说明` and confirm the result cites the
   frozen step, constraint reasons, objective trade-offs, and fallback context
   without offering a rebuild, solver, or approval action. Select `排程前检查`
   and confirm that a blocking rule remains visible and cannot be bypassed.
2. On `/orders`, select `数据质量预检` in the structured order form. Confirm
   that it reports deterministic findings and does not fill, correct, or select
   any form field.
3. On `/resources`, select `检查资源数据`. Confirm the device/employee tables
   remain unchanged while an applicability, shift, or unavailable-window
   finding is displayed.
4. On `/events`, select an event and then `获取诊断`. Confirm the right-side
   `异常诊断` drawer identifies its event context, affected work, frozen steps,
   risks, evidence, gaps, and confidence. Close the drawer before selecting any
   formal event action. After manually closing an event, select `异常案例候选`;
   edit/review the candidate and submit it only to the review queue. Confirm the
   UI states that it is not yet long-term memory or retrievable.
5. On `/admin/audit`, enter a question in `审计辅助检索`, review the generated
   editable filters, and select `应用可见筛选`. Confirm that audit entries are
   only read and that no edit/delete action exists.
6. On `/notifications`, select `生成通知草稿`, edit the body, then select
   `确认发送`. Confirm that the draft is editable before sending and that the
   final status is server-confirmed. The assistant must not choose recipients,
   channels, or send without this explicit action.

Role boundary checks: `viewer` may view schedule explanations but has no
preflight, candidate, audit-filter, or notification-send control. `operator`
has no assistance controls outside its existing execution/notification access.
`admin` and `scheduler` may access only the controls permitted by their normal
workflow; frontend visibility is not a security boundary and Phase 2 Go RBAC
must enforce the same restrictions.

## Reset And Boundaries

Role changes, query state, and fixture mutations exist only for the loaded page.
Reloading returns the session to the fixed scheduler fixture and resets the
fixture data; no browser credential, token, employee ID, password, or session
storage is created. The demo has no live API fallback: requests outside the
registered MSW fixtures are reported as unhandled.

This is a manual acceptance surface only. It is not a login mechanism and does
not grant or persist production access.
