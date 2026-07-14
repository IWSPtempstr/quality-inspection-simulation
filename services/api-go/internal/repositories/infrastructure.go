package repositories

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"gorm.io/datatypes"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type IdempotencyRepository struct{}

func (IdempotencyRepository) Find(ctx context.Context, db *gorm.DB, scope, key string) (entities.IdempotencyRecord, bool, error) {
	var model models.IdempotencyRecord
	err := db.WithContext(ctx).Where("scope = ? AND idempotency_key = ?", scope, key).First(&model).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return entities.IdempotencyRecord{}, false, nil
	}
	if err != nil {
		return entities.IdempotencyRecord{}, false, fmt.Errorf("find idempotency record: %w", err)
	}
	return entities.IdempotencyRecord{
		ID: model.ID, Scope: model.Scope, IdempotencyKey: model.IdempotencyKey, RequestHash: model.RequestHash, CreatedAt: model.CreatedAt,
	}, true, nil
}

func (IdempotencyRepository) Create(ctx context.Context, tx *gorm.DB, record entities.IdempotencyRecord) error {
	model := models.IdempotencyRecord{
		ID: record.ID, Scope: record.Scope, IdempotencyKey: record.IdempotencyKey,
		RequestHash: record.RequestHash, CreatedAt: record.CreatedAt,
	}
	if err := tx.WithContext(ctx).Create(&model).Error; err != nil {
		return fmt.Errorf("create idempotency record: %w", err)
	}
	return nil
}

func (IdempotencyRepository) CreateIfAbsent(ctx context.Context, tx *gorm.DB, record entities.IdempotencyRecord) (bool, error) {
	model := models.IdempotencyRecord{
		ID: record.ID, Scope: record.Scope, IdempotencyKey: record.IdempotencyKey,
		RequestHash: record.RequestHash, CreatedAt: record.CreatedAt,
	}
	result := tx.WithContext(ctx).Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "scope"}, {Name: "idempotency_key"}},
		DoNothing: true,
	}).Create(&model)
	if result.Error != nil {
		return false, fmt.Errorf("claim idempotency record: %w", result.Error)
	}
	return result.RowsAffected == 1, nil
}

type AuditLogRepository struct{}

func (AuditLogRepository) Append(ctx context.Context, tx *gorm.DB, log entities.AuditLog) error {
	model := models.AuditLog{
		ID: log.ID, ActorID: log.ActorID, Action: log.Action, EntityType: log.EntityType,
		EntityID: log.EntityID, RequestID: log.RequestID, CorrelationID: log.CorrelationID,
		BeforeVersion: log.BeforeVersion, AfterVersion: log.AfterVersion, Outcome: log.Outcome,
		Detail: datatypes.JSON(copyJSON(log.Detail)), CreatedAt: log.CreatedAt,
	}
	if err := tx.WithContext(ctx).Create(&model).Error; err != nil {
		return fmt.Errorf("append audit log: %w", err)
	}
	return nil
}

type OutboxRepository struct{}

func (OutboxRepository) Enqueue(ctx context.Context, tx *gorm.DB, event entities.OutboxEvent) error {
	model := models.OutboxEvent{
		ID: event.ID, EventType: event.EventType, AggregateType: event.AggregateType,
		AggregateID: event.AggregateID, Payload: datatypes.JSON(copyJSON(event.Payload)),
		OccurredAt: event.OccurredAt, PublishedAt: event.PublishedAt, CreatedAt: event.CreatedAt,
	}
	if err := tx.WithContext(ctx).Create(&model).Error; err != nil {
		return fmt.Errorf("enqueue outbox event: %w", err)
	}
	return nil
}

func (OutboxRepository) ListUnpublished(ctx context.Context, db *gorm.DB) ([]entities.OutboxEvent, error) {
	var records []models.OutboxEvent
	if err := db.WithContext(ctx).Where("published_at IS NULL").Order("occurred_at, id").Find(&records).Error; err != nil {
		return nil, fmt.Errorf("list unpublished outbox events: %w", err)
	}

	events := make([]entities.OutboxEvent, 0, len(records))
	for _, record := range records {
		events = append(events, entities.OutboxEvent{
			ID: record.ID, EventType: record.EventType, AggregateType: record.AggregateType,
			AggregateID: record.AggregateID, Payload: copyJSON(record.Payload), OccurredAt: record.OccurredAt,
			PublishedAt: record.PublishedAt, CreatedAt: record.CreatedAt,
		})
	}
	return events, nil
}

func copyJSON(value []byte) json.RawMessage {
	return append(json.RawMessage(nil), value...)
}
