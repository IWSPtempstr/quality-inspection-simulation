-- +goose Up
CREATE TABLE exception_case_reviews (
    id UUID PRIMARY KEY,
    center_id TEXT NOT NULL,
    event_id UUID NOT NULL REFERENCES system_events(id),
    submitted_by TEXT NOT NULL,
    source_candidate_hash TEXT NOT NULL,
    submission JSONB NOT NULL,
    retention_until TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status = 'pending_review'),
    version BIGINT NOT NULL DEFAULT 1,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX exception_case_reviews_center_status_idx ON exception_case_reviews(center_id, status, submitted_at DESC);
-- Candidate content remains in PostgreSQL review storage until human approval;
-- no G8 table or trigger makes it available to retrieval/indexing.
-- This migration is intentionally forward-only. Do not add a Goose Down section.
