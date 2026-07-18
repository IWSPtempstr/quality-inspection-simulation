INSERT INTO schedule_snapshots (
    id,
    center_id,
    input_hash,
    as_of,
    base_schedule_version,
    resource_snapshot_version,
    payload,
    created_at
) VALUES (
    '11111111-1111-1111-1111-111111111111',
    'center-e2e',
    'sha256:e2e-seed',
    '2026-07-17T00:00:00Z',
    0,
    1,
    '{}'::jsonb,
    now()
);

INSERT INTO schedule_previews (
    id,
    center_id,
    snapshot_id,
    status,
    candidate,
    normalized_steps,
    version,
    created_at,
    updated_at
) VALUES (
    '22222222-2222-2222-2222-222222222222',
    'center-e2e',
    '11111111-1111-1111-1111-111111111111',
    'approved_pending_writeback',
    '{}'::jsonb,
    '[
      {
        "id":"33333333-3333-3333-3333-333333333333",
        "order_id":"44444444-4444-4444-4444-444444444444",
        "project_id":"55555555-5555-5555-5555-555555555555",
        "starts_at":"2026-07-17T01:00:00Z",
        "ends_at":"2026-07-17T01:30:00Z"
      }
    ]'::jsonb,
    1,
    now(),
    now()
);

INSERT INTO outbox_events (
    id,
    event_type,
    aggregate_type,
    aggregate_id,
    payload,
    occurred_at,
    created_at
) VALUES (
    '66666666-6666-6666-6666-666666666666',
    'schedule.writeback',
    'schedule_preview',
    '22222222-2222-2222-2222-222222222222',
    '{"preview_id":"22222222-2222-2222-2222-222222222222","center_id":"center-e2e"}'::jsonb,
    now(),
    now()
);
