package models

import (
	"time"

	"gorm.io/datatypes"
)

type InboxEvent struct {
	EventID       string         `gorm:"column:event_id;primaryKey"`
	CenterID      *string        `gorm:"column:center_id"`
	EntityType    *string        `gorm:"column:entity_type"`
	EntityID      *string        `gorm:"column:entity_id"`
	SourceVersion *int64         `gorm:"column:source_version"`
	Envelope      datatypes.JSON `gorm:"column:envelope;type:jsonb;not null"`
	CorrelationID string         `gorm:"column:correlation_id;not null"`
	Status        string         `gorm:"column:status;not null"`
	RetryCount    int            `gorm:"column:retry_count;not null"`
	FailureReason *string        `gorm:"column:failure_reason"`
	ReceivedAt    time.Time      `gorm:"column:received_at;not null"`
	ProcessedAt   *time.Time     `gorm:"column:processed_at"`
}

func (InboxEvent) TableName() string { return "inbox_events" }
