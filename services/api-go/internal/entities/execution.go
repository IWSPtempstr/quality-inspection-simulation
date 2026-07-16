package entities

import (
	"encoding/json"
	"time"
)

type ScheduleStep struct {
	ID, CenterID, OrderID, ProjectID, Status string
	ScheduleVersion                          int64
	EquipmentID                              *string
	EmployeeIDs, ProjectResult               json.RawMessage
	ExecutorID                               *string
	StartsAt, EndsAt                         time.Time
	ActualStartedAt, ActualCompletedAt       *time.Time
	Version                                  int64
}

type SystemEvent struct {
	ID, CenterID, EventType, EntityType, Severity, Status string
	EntityID                                              *string
	Payload                                               json.RawMessage
	AcknowledgedBy, ClosedBy, Disposition                 *string
	AcknowledgedAt, ClosedAt                              *time.Time
	Version                                               int64
	OccurredAt                                            time.Time
}

type Notification struct {
	ID, CenterID, RecipientID, Title, Body, Channel, Status string
	OrderID                                                 *string
	ReadAt                                                  *time.Time
	Version                                                 int64
	CreatedAt                                               time.Time
}
