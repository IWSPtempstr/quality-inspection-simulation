package services

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

var ErrRetryableResourceEvent = errors.New("retryable resource event")

type Debouncer interface {
	SetFirst(context.Context, string, time.Duration) (bool, error)
}

type ResourceEventService struct {
	db        *gorm.DB
	inbox     repositories.InboxRepository
	outbox    repositories.OutboxRepository
	resources repositories.ResourceRepository
	debouncer Debouncer
}

func NewResourceEventService(db *gorm.DB, debouncer Debouncer) ResourceEventService {
	return ResourceEventService{db: db, debouncer: debouncer}
}

// Process persists receipt before any projection write. Redis must be available before the projection transaction begins.
func (s ResourceEventService) Process(ctx context.Context, raw []byte, correlationID string) (bool, error) {
	event, err := parseResourceEvent(raw)
	if err != nil {
		return false, s.quarantine(ctx, raw, correlationID, err.Error())
	}
	inbox := entities.InboxEvent{EventID: event.EventID, CenterID: event.CenterID, EntityType: event.EntityType, EntityID: event.EntityID, SourceVersion: event.SourceVersion, Envelope: append([]byte(nil), raw...), CorrelationID: correlationID, Status: entities.InboxReceived, ReceivedAt: time.Now().UTC()}
	created, err := s.inbox.CreateReceived(ctx, s.db, inbox)
	if err != nil {
		return false, retryable("record inbox event", err)
	}
	if !created {
		existing, found, err := s.inbox.Get(ctx, s.db, event.EventID)
		if err != nil {
			return false, retryable("read existing inbox event", err)
		}
		if !found {
			return false, retryable("read existing inbox event", errors.New("inbox event disappeared"))
		}
		// A redelivery of an unfinished event must resume processing. Only terminal
		// inbox states are safe to acknowledge as duplicates.
		if existing.Status != entities.InboxReceived {
			return true, nil
		}
	}

	version, exists, err := s.resources.CurrentVersion(ctx, s.db, event.EntityType, event.CenterID, event.EntityID)
	if err != nil {
		return false, retryable("read resource version", err)
	}
	if exists && event.SourceVersion <= version {
		err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error { return s.inbox.Mark(ctx, tx, event.EventID, entities.InboxStale, nil) })
		if err != nil {
			return false, retryable("mark stale inbox event", err)
		}
		return true, nil
	}
	first, err := s.debouncer.SetFirst(ctx, event.CenterID, 45*time.Second)
	if err != nil {
		return false, fmt.Errorf("%w: debounce resource event: %v", ErrRetryableResourceEvent, err)
	}

	err = s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		version, exists, err := s.resources.CurrentVersion(ctx, tx, event.EntityType, event.CenterID, event.EntityID)
		if err != nil {
			return err
		}
		if exists && event.SourceVersion <= version {
			return s.inbox.Mark(ctx, tx, event.EventID, entities.InboxStale, nil)
		}
		if err := s.apply(ctx, tx, event); err != nil {
			return err
		}
		if first {
			payload, err := json.Marshal(entities.RebuildIntent{CenterID: event.CenterID, CorrelationID: correlationID, WindowStart: time.Now().UTC(), TriggeringEventIDs: []string{event.EventID}})
			if err != nil {
				return fmt.Errorf("marshal rebuild intent: %w", err)
			}
			if err := s.outbox.Enqueue(ctx, tx, entities.OutboxEvent{ID: uuid.NewString(), EventType: "schedule.rebuild.requested", AggregateType: "resource_center", AggregateID: event.CenterID, Payload: payload, OccurredAt: time.Now().UTC(), CreatedAt: time.Now().UTC()}); err != nil {
				return err
			}
		}
		return s.inbox.Mark(ctx, tx, event.EventID, entities.InboxProcessed, nil)
	})
	if err != nil {
		return false, retryable("process resource event", err)
	}
	return true, nil
}

// RecordRetry durably increments retry_count before a worker routes the event
// through a RabbitMQ retry queue or the DLQ. It returns the persisted count.
func (s ResourceEventService) RecordRetry(ctx context.Context, raw []byte) (int, error) {
	event, err := parseResourceEvent(raw)
	if err != nil {
		return 0, err
	}
	if err := s.inbox.IncrementRetry(ctx, s.db, event.EventID); err != nil {
		return 0, retryable("increment inbox retry", err)
	}
	record, found, err := s.inbox.Get(ctx, s.db, event.EventID)
	if err != nil {
		return 0, retryable("read inbox retry", err)
	}
	if !found {
		return 0, retryable("read inbox retry", errors.New("inbox event was not recorded"))
	}
	return record.RetryCount, nil
}

func retryable(operation string, err error) error {
	return fmt.Errorf("%w: %s: %v", ErrRetryableResourceEvent, operation, err)
}

func (s ResourceEventService) quarantine(ctx context.Context, raw []byte, correlationID, reason string) error {
	id := "quarantine:" + uuid.NewString()
	if parsed := struct {
		EventID string `json:"event_id"`
	}{}; json.Unmarshal(raw, &parsed) == nil && parsed.EventID != "" {
		id = parsed.EventID
	}
	_, err := s.inbox.CreateReceived(ctx, s.db, entities.InboxEvent{EventID: id, Envelope: append([]byte(nil), raw...), CorrelationID: correlationID, Status: entities.InboxQuarantined, FailureReason: &reason, ReceivedAt: time.Now().UTC()})
	return err
}

func parseResourceEvent(raw []byte) (entities.ResourceEvent, error) {
	var event entities.ResourceEvent
	if err := json.Unmarshal(raw, &event); err != nil {
		return event, fmt.Errorf("malformed resource event: %w", err)
	}
	if event.EventID == "" || event.CenterID == "" || event.EntityID == "" || event.SourceVersion < 1 || event.OccurredAt.IsZero() || len(event.Payload) == 0 {
		return event, errors.New("resource event fields are incomplete")
	}
	if event.EventType != "upserted" && event.EventType != "deactivated" {
		return event, errors.New("unsupported resource event type")
	}
	if event.EntityType != "equipment" && event.EntityType != "employee" && event.EntityType != "shift" && event.EntityType != "unavailability" {
		return event, errors.New("unsupported resource entity type")
	}
	if !json.Valid(event.Payload) {
		return event, errors.New("invalid resource payload")
	}
	if err := validateResourcePayload(event); err != nil {
		return event, err
	}
	return event, nil
}

func validateResourcePayload(event entities.ResourceEvent) error {
	switch event.EntityType {
	case "equipment":
		var payload struct {
			Name     string `json:"name"`
			Status   string `json:"status"`
			Capacity int    `json:"capacity"`
		}
		if err := json.Unmarshal(event.Payload, &payload); err != nil || payload.Name == "" || payload.Status == "" || payload.Capacity < 1 {
			return errors.New("invalid equipment payload")
		}
	case "employee":
		var payload struct {
			Name string `json:"name"`
		}
		if err := json.Unmarshal(event.Payload, &payload); err != nil || payload.Name == "" {
			return errors.New("invalid employee payload")
		}
	case "shift":
		var payload struct {
			Name      string    `json:"name"`
			StartTime time.Time `json:"start_time"`
			EndTime   time.Time `json:"end_time"`
		}
		if err := json.Unmarshal(event.Payload, &payload); err != nil || payload.Name == "" || payload.StartTime.IsZero() || payload.EndTime.IsZero() {
			return errors.New("invalid shift payload")
		}
	case "unavailability":
		var payload struct {
			EntityID string    `json:"entity_id"`
			Reason   string    `json:"reason"`
			StartsAt time.Time `json:"starts_at"`
			EndsAt   time.Time `json:"ends_at"`
		}
		if err := json.Unmarshal(event.Payload, &payload); err != nil || payload.EntityID == "" || payload.Reason == "" || payload.StartsAt.IsZero() || payload.EndsAt.IsZero() || !payload.EndsAt.After(payload.StartsAt) {
			return errors.New("invalid unavailability payload")
		}
	}
	return nil
}

func (s ResourceEventService) apply(ctx context.Context, tx *gorm.DB, event entities.ResourceEvent) error {
	active := event.EventType == "upserted"
	now := time.Now().UTC()
	switch event.EntityType {
	case "equipment":
		var payload struct {
			Name, Status string
			Capacity     int `json:"capacity"`
		}
		if err := json.Unmarshal(event.Payload, &payload); err != nil || payload.Name == "" || payload.Status == "" || payload.Capacity < 1 {
			return errors.New("invalid equipment payload")
		}
		return s.resources.UpsertEquipment(ctx, tx, models.Equipment{ID: uuid.NewString(), CenterID: event.CenterID, SourceID: event.EntityID, Name: payload.Name, Status: payload.Status, Capacity: payload.Capacity, Active: active, SourceVersion: event.SourceVersion, CreatedAt: now, UpdatedAt: now})
	case "employee":
		var payload struct {
			Name string `json:"name"`
		}
		if err := json.Unmarshal(event.Payload, &payload); err != nil || payload.Name == "" {
			return errors.New("invalid employee payload")
		}
		return s.resources.UpsertEmployee(ctx, tx, models.Employee{ID: uuid.NewString(), CenterID: event.CenterID, SourceID: event.EntityID, Name: payload.Name, Active: active, SourceVersion: event.SourceVersion, CreatedAt: now, UpdatedAt: now})
	case "shift":
		var payload struct {
			Name      string    `json:"name"`
			StartTime time.Time `json:"start_time"`
			EndTime   time.Time `json:"end_time"`
		}
		if err := json.Unmarshal(event.Payload, &payload); err != nil || payload.Name == "" || payload.StartTime.IsZero() || payload.EndTime.IsZero() {
			return errors.New("invalid shift payload")
		}
		return s.resources.UpsertShift(ctx, tx, models.Shift{ID: uuid.NewString(), CenterID: event.CenterID, SourceID: event.EntityID, Name: payload.Name, StartTime: payload.StartTime, EndTime: payload.EndTime, Active: active, SourceVersion: event.SourceVersion})
	case "unavailability":
		var payload struct {
			EntityID string    `json:"entity_id"`
			Reason   string    `json:"reason"`
			StartsAt time.Time `json:"starts_at"`
			EndsAt   time.Time `json:"ends_at"`
		}
		if err := json.Unmarshal(event.Payload, &payload); err != nil || payload.EntityID == "" || payload.Reason == "" || payload.StartsAt.IsZero() || payload.EndsAt.IsZero() || !payload.EndsAt.After(payload.StartsAt) {
			return errors.New("invalid unavailability payload")
		}
		return s.resources.UpsertUnavailability(ctx, tx, models.Unavailability{ID: uuid.NewString(), CenterID: event.CenterID, SourceID: event.EntityID, EntityID: payload.EntityID, StartsAt: payload.StartsAt, EndsAt: payload.EndsAt, Reason: payload.Reason, Active: active, SourceVersion: event.SourceVersion})
	}
	return errors.New("unsupported resource entity type")
}
