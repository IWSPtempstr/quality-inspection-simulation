package repositories

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"gorm.io/datatypes"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type InboxRepository struct{}

func (InboxRepository) CreateReceived(ctx context.Context, db *gorm.DB, event entities.InboxEvent) (bool, error) {
	model := inboxModel(event)
	result := db.WithContext(ctx).Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "event_id"}}, DoNothing: true}).Create(&model)
	if result.Error != nil {
		return false, fmt.Errorf("create inbox event: %w", result.Error)
	}
	return result.RowsAffected == 1, nil
}

func (InboxRepository) Mark(ctx context.Context, tx *gorm.DB, eventID, status string, reason *string) error {
	now := time.Now().UTC()
	if err := tx.WithContext(ctx).Model(&models.InboxEvent{}).Where("event_id = ?", eventID).Updates(map[string]any{"status": status, "failure_reason": reason, "processed_at": now}).Error; err != nil {
		return fmt.Errorf("mark inbox event: %w", err)
	}
	return nil
}

func (InboxRepository) IncrementRetry(ctx context.Context, db *gorm.DB, eventID string) error {
	if err := db.WithContext(ctx).Model(&models.InboxEvent{}).Where("event_id = ?", eventID).UpdateColumn("retry_count", gorm.Expr("retry_count + 1")).Error; err != nil {
		return fmt.Errorf("increment inbox retry: %w", err)
	}
	return nil
}

func (InboxRepository) Get(ctx context.Context, db *gorm.DB, eventID string) (entities.InboxEvent, bool, error) {
	var record models.InboxEvent
	err := db.WithContext(ctx).First(&record, "event_id = ?", eventID).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return entities.InboxEvent{}, false, nil
	}
	if err != nil {
		return entities.InboxEvent{}, false, fmt.Errorf("get inbox event: %w", err)
	}
	return inboxEntity(record), true, nil
}

func inboxModel(event entities.InboxEvent) models.InboxEvent {
	return models.InboxEvent{EventID: event.EventID, CenterID: pointer(event.CenterID), EntityType: pointer(event.EntityType), EntityID: pointer(event.EntityID), SourceVersion: &event.SourceVersion, Envelope: datatypes.JSON(append([]byte(nil), event.Envelope...)), CorrelationID: event.CorrelationID, Status: event.Status, RetryCount: event.RetryCount, FailureReason: event.FailureReason, ReceivedAt: event.ReceivedAt, ProcessedAt: event.ProcessedAt}
}

func inboxEntity(record models.InboxEvent) entities.InboxEvent {
	return entities.InboxEvent{EventID: record.EventID, CenterID: dereference(record.CenterID), EntityType: dereference(record.EntityType), EntityID: dereference(record.EntityID), SourceVersion: dereferenceInt64(record.SourceVersion), Envelope: json.RawMessage(append([]byte(nil), record.Envelope...)), CorrelationID: record.CorrelationID, Status: record.Status, RetryCount: record.RetryCount, FailureReason: record.FailureReason, ReceivedAt: record.ReceivedAt, ProcessedAt: record.ProcessedAt}
}

func pointer(value string) *string { return &value }
func dereference(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}
func dereferenceInt64(value *int64) int64 {
	if value == nil {
		return 0
	}
	return *value
}
