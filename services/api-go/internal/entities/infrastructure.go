package entities

import (
	"encoding/json"
	"time"
)

type IdempotencyRecord struct {
	ID             string
	Scope          string
	IdempotencyKey string
	RequestHash    string
	CreatedAt      time.Time
}

type AuditLog struct {
	ID            string
	ActorID       string
	Action        string
	EntityType    string
	EntityID      string
	RequestID     string
	CorrelationID string
	BeforeVersion *int64
	AfterVersion  *int64
	Outcome       string
	Detail        json.RawMessage
	CreatedAt     time.Time
}

type OutboxEvent struct {
	ID            string
	EventType     string
	AggregateType string
	AggregateID   string
	Payload       json.RawMessage
	OccurredAt    time.Time
	PublishedAt   *time.Time
	CreatedAt     time.Time
}
