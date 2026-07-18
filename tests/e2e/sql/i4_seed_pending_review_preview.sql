INSERT INTO schedule_snapshots (id, center_id, input_hash, as_of, base_schedule_version, resource_snapshot_version, payload, created_at)
VALUES ('00000000-0000-0000-0000-000000000401', 'center-i4', 'hash-i4-approval-race', '2026-07-17T13:00:00Z', 0, 1, '{}'::jsonb, now());

INSERT INTO schedule_previews (id, center_id, snapshot_id, status, candidate, normalized_steps, normalized_result_hash, version, created_at, updated_at)
VALUES (
  '00000000-0000-0000-0000-000000000402',
  'center-i4',
  '00000000-0000-0000-0000-000000000401',
  'pending_review',
  '{"schedule":{"steps":[{"id":"00000000-0000-0000-0000-000000000406","order_id":"00000000-0000-0000-0000-000000000404","project_id":"00000000-0000-0000-0000-000000000405","equipment_id":"00000000-0000-0000-0000-000000000407","employee_ids":[],"starts_at":"2026-07-17T14:00:00Z","ends_at":"2026-07-17T15:00:00Z"}]}}'::jsonb,
  '[{"id":"00000000-0000-0000-0000-000000000406","order_id":"00000000-0000-0000-0000-000000000404","project_id":"00000000-0000-0000-0000-000000000405","equipment_id":"00000000-0000-0000-0000-000000000407","employee_ids":[],"starts_at":"2026-07-17T14:00:00Z","ends_at":"2026-07-17T15:00:00Z"}]'::jsonb,
  'sha256:i4-race',
  1,
  now(),
  now()
);
