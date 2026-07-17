-- +goose Up
ALTER TABLE schedule_previews
    ADD COLUMN normalized_result_hash TEXT NULL;

CREATE UNIQUE INDEX schedule_previews_callback_identity_idx
    ON schedule_previews (id, version, normalized_result_hash)
    WHERE normalized_result_hash IS NOT NULL;
-- This migration is intentionally forward-only. Do not add a Goose Down section.
