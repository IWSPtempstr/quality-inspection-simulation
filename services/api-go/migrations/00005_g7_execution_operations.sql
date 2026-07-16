-- +goose Up
CREATE TABLE schedule_steps (
    id UUID PRIMARY KEY,
    center_id TEXT NOT NULL,
    schedule_version BIGINT NOT NULL,
    order_id UUID NOT NULL,
    project_id UUID NOT NULL,
    equipment_id UUID NULL,
    employee_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('scheduled','running','completed','cancelled')),
    executor_id TEXT NULL,
    actual_started_at TIMESTAMPTZ NULL,
    actual_completed_at TIMESTAMPTZ NULL,
    project_result JSONB NULL,
    version BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    -- id is an execution-row identity. The formal schedule JSON remains immutable
    -- and may reuse a logical step id in a later formal version.
);
CREATE INDEX schedule_steps_center_order_idx ON schedule_steps(center_id, order_id);

CREATE TABLE system_events (
    id UUID PRIMARY KEY,
    center_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    entity_id TEXT NULL,
    status TEXT NOT NULL CHECK (status IN ('open','acknowledged','closed')),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    acknowledged_by TEXT NULL,
    acknowledged_at TIMESTAMPTZ NULL,
    closed_by TEXT NULL,
    closed_at TIMESTAMPTZ NULL,
    disposition TEXT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX system_events_center_idx ON system_events(center_id, occurred_at DESC);

CREATE TABLE notifications (
    id UUID PRIMARY KEY,
    center_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    order_id UUID NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('in_app','webhook_stub')),
    status TEXT NOT NULL CHECK (status IN ('pending','sent','failed')),
    read_at TIMESTAMPTZ NULL,
    version BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX notifications_recipient_idx ON notifications(center_id, recipient_id, created_at DESC);
CREATE TABLE center_scheduler_users (
    center_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (center_id, user_id)
);
CREATE TABLE notification_deliveries (
    id UUID PRIMARY KEY,
    notification_id UUID NOT NULL REFERENCES notifications(id),
    channel TEXT NOT NULL CHECK (channel IN ('in_app','webhook_stub')),
    status TEXT NOT NULL CHECK (status IN ('pending','sent','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT NULL,
    sent_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX notification_deliveries_notification_channel_key
    ON notification_deliveries(notification_id, channel);
-- This migration is intentionally forward-only. Do not add a Goose Down section.
