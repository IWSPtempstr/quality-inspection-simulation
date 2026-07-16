-- +goose Up
CREATE TABLE inbox_events (
    event_id TEXT PRIMARY KEY,
    center_id TEXT NULL,
    entity_type TEXT NULL,
    entity_id TEXT NULL,
    source_version BIGINT NULL,
    envelope JSONB NOT NULL,
    correlation_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('received', 'processed', 'stale', 'quarantined')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ NULL
);
CREATE INDEX inbox_events_resource_version_idx
ON inbox_events (center_id, entity_type, entity_id, source_version);

ALTER TABLE outbox_events ADD COLUMN claimed_at TIMESTAMPTZ NULL;
CREATE INDEX outbox_events_claimable_idx
ON outbox_events (occurred_at, id)
WHERE published_at IS NULL AND claimed_at IS NULL;

-- This migration is intentionally forward-only. Do not add a Goose Down section.
