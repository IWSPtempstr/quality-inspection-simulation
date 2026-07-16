package repositories

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"gorm.io/datatypes"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"time"
)

type ExecutionRepository struct{}

func (ExecutionRepository) CreateSteps(ctx context.Context, tx *gorm.DB, steps []entities.ScheduleStep) error {
	for _, step := range steps {
		if err := tx.WithContext(ctx).Create(&models.ScheduleStep{ID: step.ID, CenterID: step.CenterID, ScheduleVersion: step.ScheduleVersion, OrderID: step.OrderID, ProjectID: step.ProjectID, EquipmentID: step.EquipmentID, EmployeeIDs: datatypes.JSON(step.EmployeeIDs), StartsAt: step.StartsAt, EndsAt: step.EndsAt, Status: step.Status, Version: step.Version}).Error; err != nil {
			return err
		}
	}
	return nil
}
func (ExecutionRepository) Step(ctx context.Context, db *gorm.DB, center, id string, lock bool) (entities.ScheduleStep, error) {
	q := db.WithContext(ctx)
	if lock {
		q = q.Clauses(clause.Locking{Strength: "UPDATE"})
	}
	var m models.ScheduleStep
	if err := q.Where("center_id = ? AND id = ?", center, id).First(&m).Error; err != nil {
		return entities.ScheduleStep{}, err
	}
	return stepEntity(m), nil
}
func (ExecutionRepository) UpdateStep(ctx context.Context, tx *gorm.DB, s entities.ScheduleStep, expected int64) error {
	r := tx.WithContext(ctx).Model(&models.ScheduleStep{}).Where("id = ? AND center_id = ? AND version = ?", s.ID, s.CenterID, expected).Updates(map[string]any{"status": s.Status, "executor_id": s.ExecutorID, "actual_started_at": s.ActualStartedAt, "actual_completed_at": s.ActualCompletedAt, "project_result": datatypes.JSON(s.ProjectResult), "version": s.Version, "updated_at": time.Now().UTC()})
	if r.Error != nil {
		return r.Error
	}
	if r.RowsAffected != 1 {
		return entities.ErrVersionConflict
	}
	return nil
}
func (ExecutionRepository) CreateEvent(ctx context.Context, tx *gorm.DB, e entities.SystemEvent) error {
	return tx.WithContext(ctx).Create(&models.SystemEvent{ID: e.ID, CenterID: e.CenterID, EventType: e.EventType, EntityType: e.EntityType, Severity: e.Severity, EntityID: e.EntityID, Status: e.Status, Payload: datatypes.JSON(e.Payload), Version: e.Version, OccurredAt: e.OccurredAt, CreatedAt: e.OccurredAt, UpdatedAt: e.OccurredAt}).Error
}
func (ExecutionRepository) Event(ctx context.Context, db *gorm.DB, center, id string, lock bool) (entities.SystemEvent, error) {
	q := db.WithContext(ctx)
	if lock {
		q = q.Clauses(clause.Locking{Strength: "UPDATE"})
	}
	var m models.SystemEvent
	if err := q.Where("center_id = ? AND id = ?", center, id).First(&m).Error; err != nil {
		return entities.SystemEvent{}, err
	}
	return eventEntity(m), nil
}
func (ExecutionRepository) UpdateEvent(ctx context.Context, tx *gorm.DB, e entities.SystemEvent, expected int64) error {
	r := tx.WithContext(ctx).Model(&models.SystemEvent{}).Where("id=? AND center_id=? AND version=?", e.ID, e.CenterID, expected).Updates(map[string]any{"status": e.Status, "acknowledged_by": e.AcknowledgedBy, "acknowledged_at": e.AcknowledgedAt, "closed_by": e.ClosedBy, "closed_at": e.ClosedAt, "disposition": e.Disposition, "version": e.Version, "updated_at": time.Now().UTC()})
	if r.Error != nil {
		return r.Error
	}
	if r.RowsAffected != 1 {
		return entities.ErrVersionConflict
	}
	return nil
}
func (ExecutionRepository) ListEvents(ctx context.Context, db *gorm.DB, center string) ([]entities.SystemEvent, error) {
	var ms []models.SystemEvent
	if err := db.WithContext(ctx).Where("center_id=?", center).Order("occurred_at DESC").Find(&ms).Error; err != nil {
		return nil, err
	}
	out := make([]entities.SystemEvent, 0, len(ms))
	for _, m := range ms {
		out = append(out, eventEntity(m))
	}
	return out, nil
}
func (ExecutionRepository) CreateNotification(ctx context.Context, tx *gorm.DB, n entities.Notification) error {
	return tx.WithContext(ctx).Create(&models.Notification{ID: n.ID, CenterID: n.CenterID, RecipientID: n.RecipientID, OrderID: n.OrderID, Title: n.Title, Body: n.Body, Channel: n.Channel, Status: n.Status, Version: n.Version, CreatedAt: n.CreatedAt, UpdatedAt: n.CreatedAt}).Error
}
func (ExecutionRepository) CreateDelivery(ctx context.Context, tx *gorm.DB, id, notificationID, channel string, now time.Time) error {
	return tx.WithContext(ctx).Create(&models.NotificationDelivery{ID: id, NotificationID: notificationID, Channel: channel, Status: "pending", CreatedAt: now, UpdatedAt: now}).Error
}
func (ExecutionRepository) SchedulerRecipients(ctx context.Context, db *gorm.DB, center string) ([]string, error) {
	var ids []string
	if err := db.WithContext(ctx).Table("center_scheduler_users").Where("center_id=?", center).Pluck("user_id", &ids).Error; err != nil {
		return nil, err
	}
	return ids, nil
}
func (ExecutionRepository) ListNotifications(ctx context.Context, db *gorm.DB, center, recipient string) ([]entities.Notification, error) {
	var ms []models.Notification
	if err := db.WithContext(ctx).Where("center_id=? AND recipient_id=?", center, recipient).Order("created_at DESC").Find(&ms).Error; err != nil {
		return nil, err
	}
	out := make([]entities.Notification, 0, len(ms))
	for _, m := range ms {
		out = append(out, notificationEntity(m))
	}
	return out, nil
}
func (ExecutionRepository) MarkRead(ctx context.Context, tx *gorm.DB, center, recipient, id string) error {
	var notification models.Notification
	if err := tx.WithContext(ctx).Where("id=? AND center_id=? AND recipient_id=?", id, center, recipient).First(&notification).Error; err != nil {
		return err
	}
	if notification.ReadAt != nil {
		return nil
	}
	return tx.WithContext(ctx).Model(&models.Notification{}).Where("id=? AND center_id=? AND recipient_id=?", id, center, recipient).Update("read_at", time.Now().UTC()).Error
}
func stepEntity(m models.ScheduleStep) entities.ScheduleStep {
	return entities.ScheduleStep{ID: m.ID, CenterID: m.CenterID, ScheduleVersion: m.ScheduleVersion, OrderID: m.OrderID, ProjectID: m.ProjectID, EquipmentID: m.EquipmentID, EmployeeIDs: json.RawMessage(m.EmployeeIDs), StartsAt: m.StartsAt, EndsAt: m.EndsAt, Status: m.Status, ExecutorID: m.ExecutorID, ActualStartedAt: m.ActualStartedAt, ActualCompletedAt: m.ActualCompletedAt, ProjectResult: json.RawMessage(m.ProjectResult), Version: m.Version}
}
func eventEntity(m models.SystemEvent) entities.SystemEvent {
	return entities.SystemEvent{ID: m.ID, CenterID: m.CenterID, EventType: m.EventType, EntityType: m.EntityType, Severity: m.Severity, EntityID: m.EntityID, Status: m.Status, Payload: json.RawMessage(m.Payload), AcknowledgedBy: m.AcknowledgedBy, AcknowledgedAt: m.AcknowledgedAt, ClosedBy: m.ClosedBy, ClosedAt: m.ClosedAt, Disposition: m.Disposition, Version: m.Version, OccurredAt: m.OccurredAt}
}
func notificationEntity(m models.Notification) entities.Notification {
	return entities.Notification{ID: m.ID, CenterID: m.CenterID, RecipientID: m.RecipientID, OrderID: m.OrderID, Title: m.Title, Body: m.Body, Channel: m.Channel, Status: m.Status, ReadAt: m.ReadAt, Version: m.Version, CreatedAt: m.CreatedAt}
}

var _ = fmt.Sprintf
