-- +goose Up
CREATE TABLE schedule_snapshots (
    id UUID PRIMARY KEY,
    center_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    base_schedule_version BIGINT NOT NULL,
    resource_snapshot_version BIGINT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (center_id, input_hash)
);
CREATE TABLE schedule_previews (
    id UUID PRIMARY KEY,
    center_id TEXT NOT NULL,
    snapshot_id UUID NOT NULL REFERENCES schedule_snapshots(id),
    status TEXT NOT NULL CHECK (status IN ('pending_candidate','pending_review','rejected','approved_pending_writeback','approved','conflicted','failed')),
    candidate JSONB NULL,
    normalized_steps JSONB NULL,
    version BIGINT NOT NULL DEFAULT 1,
    partner_failure TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX schedule_previews_center_idx ON schedule_previews(center_id, created_at DESC);
CREATE TABLE schedule_versions (
    id UUID PRIMARY KEY,
    center_id TEXT NOT NULL,
    version BIGINT NOT NULL,
    preview_id UUID NOT NULL REFERENCES schedule_previews(id),
    steps JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (center_id, version)
);
CREATE TABLE schedule_preview_changes (
    id UUID PRIMARY KEY,
    preview_id UUID NOT NULL REFERENCES schedule_previews(id),
    version BIGINT NOT NULL,
    action TEXT NOT NULL,
    detail JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- This migration is intentionally forward-only. Do not add a Goose Down section.
