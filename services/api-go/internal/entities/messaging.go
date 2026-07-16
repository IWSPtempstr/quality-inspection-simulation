package entities

import (
	"encoding/json"
	"time"
)

const (
	InboxReceived    = "received"
	InboxProcessed   = "processed"
	InboxStale       = "stale"
	InboxQuarantined = "quarantined"
)

type ResourceEvent struct {
	EventID       string          `json:"event_id"`
	CenterID      string          `json:"center_id"`
	EventType     string          `json:"event_type"`
	EntityType    string          `json:"entity_type"`
	EntityID      string          `json:"entity_id"`
	SourceVersion int64           `json:"source_version"`
	OccurredAt    time.Time       `json:"occurred_at"`
	Payload       json.RawMessage `json:"payload"`
}

type InboxEvent struct {
	EventID, CenterID, EntityType, EntityID, CorrelationID, Status string
	SourceVersion                                                  int64
	Envelope                                                       json.RawMessage
	RetryCount                                                     int
	FailureReason                                                  *string
	ReceivedAt                                                     time.Time
	ProcessedAt                                                    *time.Time
}

type RebuildIntent struct {
	CenterID           string    `json:"center_id"`
	CorrelationID      string    `json:"correlation_id"`
	WindowStart        time.Time `json:"window_start"`
	TriggeringEventIDs []string  `json:"triggering_event_ids"`
}
