package services

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

var ErrInvalidExecutionTransition = errors.New("invalid execution transition")
var ErrInvalidEventTransition = errors.New("invalid event transition")

type ExecutionService struct {
	db     *gorm.DB
	repo   repositories.ExecutionRepository
	outbox repositories.OutboxRepository
	audit  AuditService
}

func NewExecutionService(db *gorm.DB) ExecutionService { return ExecutionService{db: db} }

func (s ExecutionService) Start(ctx context.Context, actor entities.Actor, id string, expected int64) (entities.ScheduleStep, error) {
	return s.stepTransition(ctx, actor, id, expected, "running", nil)
}
func (s ExecutionService) Complete(ctx context.Context, actor entities.Actor, id string, expected int64, result json.RawMessage) (entities.ScheduleStep, error) {
	if len(result) > 0 && !json.Valid(result) {
		return entities.ScheduleStep{}, fmt.Errorf("invalid project result")
	}
	return s.stepTransition(ctx, actor, id, expected, "completed", result)
}
func (s ExecutionService) stepTransition(ctx context.Context, actor entities.Actor, id string, expected int64, to string, result json.RawMessage) (entities.ScheduleStep, error) {
	var out entities.ScheduleStep
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		step, err := s.repo.Step(ctx, tx, actor.CenterID, id, true)
		if err != nil {
			return err
		}
		if step.Version != expected {
			return entities.ErrVersionConflict
		}
		if (to == "running" && step.Status != "scheduled") || (to == "completed" && step.Status != "running") {
			return ErrInvalidExecutionTransition
		}
		before := step.Version
		now := time.Now().UTC()
		step.Status = to
		step.Version++
		if to == "running" {
			step.ExecutorID = &actor.ID
			step.ActualStartedAt = &now
		} else {
			step.ActualCompletedAt = &now
			step.ProjectResult = append(json.RawMessage(nil), result...)
		}
		if err = s.repo.UpdateStep(ctx, tx, step, before); err != nil {
			return err
		}
		if err = s.notifyStep(ctx, tx, actor, step, to, now); err != nil {
			return err
		}
		if err = s.outbox.Enqueue(ctx, tx, entities.OutboxEvent{ID: uuid.NewString(), EventType: "schedule.step." + to, AggregateType: "schedule_step", AggregateID: step.ID, Payload: mustJSON(map[string]any{"center_id": step.CenterID, "step_id": step.ID, "status": step.Status}), OccurredAt: now, CreatedAt: now}); err != nil {
			return err
		}
		if err = s.audit.Append(ctx, tx, AuditEntry{Actor: actor, Action: "schedule_step_" + to, EntityType: "schedule_step", EntityID: step.ID, BeforeVersion: &before, AfterVersion: &step.Version, Outcome: "success", Detail: []byte("{}")}); err != nil {
			return err
		}
		out = step
		return nil
	})
	return out, err
}

// notifyStep uses only persisted order ownership plus the acting scheduler role;
// map-based de-duplication keeps a scheduler who created the order to one delivery.
func (s ExecutionService) notifyStep(ctx context.Context, tx *gorm.DB, actor entities.Actor, step entities.ScheduleStep, action string, now time.Time) error {
	return s.notifyRecipients(ctx, tx, actor, step.CenterID, &step.OrderID, action, now)
}

func (s ExecutionService) notifyRecipients(ctx context.Context, tx *gorm.DB, actor entities.Actor, center string, orderID *string, action string, now time.Time) error {
	var creator string
	if orderID != nil && *orderID != "" {
		if err := tx.WithContext(ctx).Table("orders").Select("created_by").Where("id=? AND center_id=?", *orderID, center).Scan(&creator).Error; err != nil {
			return err
		}
	}
	recipients := map[string]struct{}{}
	if creator != "" {
		recipients[creator] = struct{}{}
	}
	schedulers, err := s.repo.SchedulerRecipients(ctx, tx, center)
	if err != nil {
		return err
	}
	for _, scheduler := range schedulers {
		recipients[scheduler] = struct{}{}
	}
	for _, r := range actor.Roles {
		if r == entities.RoleScheduler {
			recipients[actor.ID] = struct{}{}
		}
	}
	for recipient := range recipients {
		n := entities.Notification{ID: uuid.NewString(), CenterID: center, RecipientID: recipient, OrderID: orderID, Title: "Schedule step " + action, Body: "A schedule step changed state.", Channel: "in_app", Status: "pending", Version: 1, CreatedAt: now}
		if err := s.repo.CreateNotification(ctx, tx, n); err != nil {
			return err
		}
		if err := s.repo.CreateDelivery(ctx, tx, uuid.NewString(), n.ID, n.Channel, now); err != nil {
			return err
		}
		if err := s.outbox.Enqueue(ctx, tx, entities.OutboxEvent{ID: uuid.NewString(), EventType: "notification.delivery.requested", AggregateType: "notification", AggregateID: n.ID, Payload: mustJSON(map[string]any{"center_id": n.CenterID, "notification_id": n.ID, "channel": n.Channel}), OccurredAt: now, CreatedAt: now}); err != nil {
			return err
		}
	}
	return nil
}

func (s ExecutionService) notifyEvent(ctx context.Context, tx *gorm.DB, actor entities.Actor, e entities.SystemEvent, action string, now time.Time) error {
	var orderID *string
	if e.EntityID != nil {
		switch e.EntityType {
		case "order":
			orderID = e.EntityID
		case "schedule_step":
			step, err := s.repo.Step(ctx, tx, e.CenterID, *e.EntityID, false)
			if err == nil {
				orderID = &step.OrderID
			} else if !errors.Is(err, gorm.ErrRecordNotFound) {
				return err
			}
		}
	}
	return s.notifyRecipients(ctx, tx, actor, e.CenterID, orderID, "event_"+action, now)
}

func (s ExecutionService) AcknowledgeEvent(ctx context.Context, actor entities.Actor, id string, expected int64) (entities.SystemEvent, error) {
	return s.eventTransition(ctx, actor, id, expected, "acknowledged", "")
}
func (s ExecutionService) CloseEvent(ctx context.Context, actor entities.Actor, id string, expected int64, disposition string) (entities.SystemEvent, error) {
	if strings.TrimSpace(disposition) == "" {
		return entities.SystemEvent{}, fmt.Errorf("event disposition is required")
	}
	return s.eventTransition(ctx, actor, id, expected, "closed", disposition)
}
func (s ExecutionService) eventTransition(ctx context.Context, actor entities.Actor, id string, expected int64, to, disposition string) (entities.SystemEvent, error) {
	var out entities.SystemEvent
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		e, err := s.repo.Event(ctx, tx, actor.CenterID, id, true)
		if err != nil {
			return err
		}
		if e.Version != expected {
			return entities.ErrVersionConflict
		}
		allowed := (to == "acknowledged" && e.Status == "open") || (to == "closed" && (e.Status == "open" || e.Status == "acknowledged"))
		if !allowed {
			return ErrInvalidEventTransition
		}
		before := e.Version
		now := time.Now().UTC()
		e.Status = to
		e.Version++
		if to == "acknowledged" {
			e.AcknowledgedBy = &actor.ID
			e.AcknowledgedAt = &now
		} else {
			e.ClosedBy = &actor.ID
			e.ClosedAt = &now
			e.Disposition = &disposition
		}
		if err = s.repo.UpdateEvent(ctx, tx, e, before); err != nil {
			return err
		}
		if err = s.notifyEvent(ctx, tx, actor, e, to, now); err != nil {
			return err
		}
		if err = s.outbox.Enqueue(ctx, tx, entities.OutboxEvent{ID: uuid.NewString(), EventType: "system.event." + to, AggregateType: "system_event", AggregateID: e.ID, Payload: mustJSON(map[string]any{"center_id": e.CenterID, "event_id": e.ID, "status": e.Status}), OccurredAt: now, CreatedAt: now}); err != nil {
			return err
		}
		if err = s.audit.Append(ctx, tx, AuditEntry{Actor: actor, Action: "system_event_" + to, EntityType: "system_event", EntityID: e.ID, BeforeVersion: &before, AfterVersion: &e.Version, Outcome: "success", Detail: []byte("{}")}); err != nil {
			return err
		}
		out = e
		return nil
	})
	return out, err
}
func (s ExecutionService) Events(ctx context.Context, actor entities.Actor) ([]entities.SystemEvent, error) {
	return s.repo.ListEvents(ctx, s.db, actor.CenterID)
}
func (s ExecutionService) Event(ctx context.Context, actor entities.Actor, id string) (entities.SystemEvent, error) {
	return s.repo.Event(ctx, s.db, actor.CenterID, id, false)
}
func (s ExecutionService) Notifications(ctx context.Context, actor entities.Actor) ([]entities.Notification, error) {
	return s.repo.ListNotifications(ctx, s.db, actor.CenterID, actor.ID)
}
func (s ExecutionService) MarkRead(ctx context.Context, actor entities.Actor, id string) error {
	return s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := s.repo.MarkRead(ctx, tx, actor.CenterID, actor.ID, id); err != nil {
			return err
		}
		now := time.Now().UTC()
		if err := s.outbox.Enqueue(ctx, tx, entities.OutboxEvent{ID: uuid.NewString(), EventType: "notification.read", AggregateType: "notification", AggregateID: id, Payload: mustJSON(map[string]any{"center_id": actor.CenterID, "notification_id": id}), OccurredAt: now, CreatedAt: now}); err != nil {
			return err
		}
		return s.audit.Append(ctx, tx, AuditEntry{Actor: actor, Action: "notification_read", EntityType: "notification", EntityID: id, Outcome: "success", Detail: []byte("{}")})
	})
}

// CreateExecutionEvent is the deterministic internal entry point used by execution and resource adapters.
func (s ExecutionService) CreateExecutionEvent(ctx context.Context, center, eventType, entityType, severity, entityID string, payload json.RawMessage) (entities.SystemEvent, error) {
	if !json.Valid(payload) {
		return entities.SystemEvent{}, fmt.Errorf("invalid event payload")
	}
	now := time.Now().UTC()
	e := entities.SystemEvent{ID: uuid.NewString(), CenterID: center, EventType: eventType, EntityType: entityType, Severity: severity, EntityID: &entityID, Status: "open", Payload: append(json.RawMessage(nil), payload...), Version: 1, OccurredAt: now}
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := s.repo.CreateEvent(ctx, tx, e); err != nil {
			return err
		}
		if err := s.notifyEvent(ctx, tx, entities.Actor{CenterID: center}, e, "opened", now); err != nil {
			return err
		}
		if err := s.outbox.Enqueue(ctx, tx, entities.OutboxEvent{ID: uuid.NewString(), EventType: "system.event.opened", AggregateType: "system_event", AggregateID: e.ID, Payload: mustJSON(map[string]any{"center_id": center, "event_id": e.ID}), OccurredAt: now, CreatedAt: now}); err != nil {
			return err
		}
		return s.audit.Append(ctx, tx, AuditEntry{Actor: entities.Actor{ID: "system", CenterID: center}, Action: "system_event_opened", EntityType: "system_event", EntityID: e.ID, Outcome: "success", Detail: []byte("{}")})
	})
	return e, err
}
func mustJSON(v any) json.RawMessage { b, _ := json.Marshal(v); return b }
