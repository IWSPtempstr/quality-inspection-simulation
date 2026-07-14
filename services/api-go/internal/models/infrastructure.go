package models

import (
	"time"

	"gorm.io/datatypes"
)

type IdempotencyRecord struct {
	ID             string    `gorm:"column:id;type:uuid;primaryKey"`
	Scope          string    `gorm:"column:scope;not null"`
	IdempotencyKey string    `gorm:"column:idempotency_key;not null"`
	RequestHash    string    `gorm:"column:request_hash;not null"`
	CreatedAt      time.Time `gorm:"column:created_at;not null"`
}

func (IdempotencyRecord) TableName() string { return "idempotency_records" }

type AuditLog struct {
	ID            string         `gorm:"column:id;type:uuid;primaryKey"`
	ActorID       string         `gorm:"column:actor_id;not null"`
	Action        string         `gorm:"column:action;not null"`
	EntityType    string         `gorm:"column:entity_type;not null"`
	EntityID      string         `gorm:"column:entity_id;not null"`
	RequestID     string         `gorm:"column:request_id;not null"`
	CorrelationID string         `gorm:"column:correlation_id;not null"`
	BeforeVersion *int64         `gorm:"column:before_version"`
	AfterVersion  *int64         `gorm:"column:after_version"`
	Outcome       string         `gorm:"column:outcome;not null"`
	Detail        datatypes.JSON `gorm:"column:detail;type:jsonb;not null"`
	CreatedAt     time.Time      `gorm:"column:created_at;not null"`
}

func (AuditLog) TableName() string { return "audit_logs" }

type OutboxEvent struct {
	ID            string         `gorm:"column:id;type:uuid;primaryKey"`
	EventType     string         `gorm:"column:event_type;not null"`
	AggregateType string         `gorm:"column:aggregate_type;not null"`
	AggregateID   string         `gorm:"column:aggregate_id;not null"`
	Payload       datatypes.JSON `gorm:"column:payload;type:jsonb;not null"`
	OccurredAt    time.Time      `gorm:"column:occurred_at;not null"`
	PublishedAt   *time.Time     `gorm:"column:published_at"`
	CreatedAt     time.Time      `gorm:"column:created_at;not null"`
}

func (OutboxEvent) TableName() string { return "outbox_events" }
