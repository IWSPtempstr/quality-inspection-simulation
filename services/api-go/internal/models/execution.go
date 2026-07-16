package models

import (
	"gorm.io/datatypes"
	"time"
)

type ScheduleStep struct {
	ID, CenterID, OrderID, ProjectID, Status string
	ScheduleVersion                          int64
	EquipmentID                              *string
	EmployeeIDs, ProjectResult               datatypes.JSON
	ExecutorID                               *string
	StartsAt, EndsAt                         time.Time
	ActualStartedAt, ActualCompletedAt       *time.Time
	Version                                  int64
	CreatedAt, UpdatedAt                     time.Time
}

func (ScheduleStep) TableName() string { return "schedule_steps" }

type SystemEvent struct {
	ID, CenterID, EventType, EntityType, Severity, Status string
	EntityID                                              *string
	Payload                                               datatypes.JSON
	AcknowledgedBy, ClosedBy, Disposition                 *string
	AcknowledgedAt, ClosedAt                              *time.Time
	Version                                               int64
	OccurredAt, CreatedAt, UpdatedAt                      time.Time
}

func (SystemEvent) TableName() string { return "system_events" }

type Notification struct {
	ID, CenterID, RecipientID, Title, Body, Channel, Status string
	OrderID                                                 *string
	ReadAt                                                  *time.Time
	Version                                                 int64
	CreatedAt, UpdatedAt                                    time.Time
}

func (Notification) TableName() string { return "notifications" }

type NotificationDelivery struct {
	ID, NotificationID, Channel, Status string
	Attempts                            int
	FailureReason                       *string
	SentAt                              *time.Time
	CreatedAt, UpdatedAt                time.Time
}

func (NotificationDelivery) TableName() string { return "notification_deliveries" }
