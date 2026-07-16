-- +goose Up
ALTER TABLE idempotency_records
    ADD COLUMN response_status INTEGER NULL,
    ADD COLUMN response_content_type TEXT NULL,
    ADD COLUMN response_body TEXT NULL,
    ADD COLUMN completed_at TIMESTAMPTZ NULL;

CREATE TABLE detection_projects (
    id UUID PRIMARY KEY,
    source_id TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    source_version BIGINT NOT NULL,
    effective_from TIMESTAMPTZ NULL,
    effective_to TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE project_certification_types (
    project_id UUID NOT NULL REFERENCES detection_projects(id),
    certification_type TEXT NOT NULL CHECK (certification_type IN ('CCC','CVC','international')),
    PRIMARY KEY (project_id, certification_type)
);
CREATE TABLE center_projects (
    center_id TEXT NOT NULL,
    project_id UUID NOT NULL REFERENCES detection_projects(id),
    active BOOLEAN NOT NULL DEFAULT true,
    source_version BIGINT NOT NULL,
    effective_from TIMESTAMPTZ NULL,
    effective_to TIMESTAMPTZ NULL,
    PRIMARY KEY (center_id, project_id)
);

CREATE TABLE orders (
    id UUID PRIMARY KEY,
    center_id TEXT NOT NULL,
    sample_name TEXT NOT NULL,
    sample_quantity INTEGER NOT NULL CHECK (sample_quantity > 0),
    certification_type TEXT NOT NULL CHECK (certification_type IN ('CCC','CVC','international')),
    priority TEXT NOT NULL CHECK (priority IN ('normal','urgent','vip')),
    promised_finish_time TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending_schedule','scheduled','in_progress','paused','completed','cancelled')),
    version BIGINT NOT NULL DEFAULT 1,
    source_order_id UUID NULL REFERENCES orders(id),
    pause_reason TEXT NULL,
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX orders_center_status_idx ON orders (center_id, status, promised_finish_time);
CREATE TABLE order_projects (
    id UUID PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES orders(id),
    project_id UUID NOT NULL REFERENCES detection_projects(id),
    status TEXT NOT NULL CHECK (status IN ('pending','scheduled','running','completed','retest_required','failed','cancelled')),
    source_order_project_id UUID NULL REFERENCES order_projects(id),
    retest_order_id UUID NULL REFERENCES orders(id),
    version BIGINT NOT NULL DEFAULT 1,
    UNIQUE (order_id, project_id)
);

CREATE TABLE equipment (
    id UUID PRIMARY KEY, center_id TEXT NOT NULL, source_id TEXT NOT NULL,
    name TEXT NOT NULL, status TEXT NOT NULL, capacity INTEGER NOT NULL CHECK (capacity > 0),
    active BOOLEAN NOT NULL DEFAULT true, source_version BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (center_id, source_id)
);
CREATE TABLE equipment_projects (equipment_id UUID NOT NULL REFERENCES equipment(id), project_id UUID NOT NULL REFERENCES detection_projects(id), PRIMARY KEY (equipment_id, project_id));
CREATE TABLE employees (
    id UUID PRIMARY KEY, center_id TEXT NOT NULL, source_id TEXT NOT NULL, name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true, source_version BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (center_id, source_id)
);
CREATE TABLE employee_skills (employee_id UUID NOT NULL REFERENCES employees(id), project_id UUID NOT NULL REFERENCES detection_projects(id), PRIMARY KEY (employee_id, project_id));
CREATE TABLE shifts (
    id UUID PRIMARY KEY, center_id TEXT NOT NULL, source_id TEXT NOT NULL, name TEXT NOT NULL,
    start_time TIME NOT NULL, end_time TIME NOT NULL, active BOOLEAN NOT NULL DEFAULT true,
    source_version BIGINT NOT NULL, UNIQUE (center_id, source_id)
);
CREATE TABLE unavailability (
    id UUID PRIMARY KEY, center_id TEXT NOT NULL, source_id TEXT NOT NULL, entity_id UUID NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL, ends_at TIMESTAMPTZ NOT NULL, reason TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true, source_version BIGINT NOT NULL, UNIQUE (center_id, source_id)
);
