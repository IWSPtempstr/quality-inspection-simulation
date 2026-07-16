package services

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"gorm.io/gorm"
)

type ConfirmingPublisher interface {
	PublishConfirmed(context.Context, string, []byte, string) error
}
type OutboxPublisher struct {
	db         *gorm.DB
	repository repositories.OutboxRepository
	publisher  ConfirmingPublisher
}

func NewOutboxPublisher(db *gorm.DB, publisher ConfirmingPublisher) OutboxPublisher {
	return OutboxPublisher{db: db, publisher: publisher}
}

func (p OutboxPublisher) PublishPending(ctx context.Context, limit int) error {
	var events []entities.OutboxEvent
	if err := p.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var err error
		events, err = p.repository.ClaimUnpublished(ctx, tx, limit)
		return err
	}); err != nil {
		return err
	}
	for index, event := range events {
		routingKey, correlationID, err := outboxRouting(event)
		if err != nil {
			_ = p.repository.ReleaseClaim(ctx, p.db, event.ID)
			continue
		}
		if err := p.publisher.PublishConfirmed(ctx, routingKey, event.Payload, correlationID); err != nil {
			p.releaseClaims(ctx, events[index:])
			return err
		}
		if err := p.repository.MarkPublished(ctx, p.db, event.ID); err != nil {
			p.releaseClaims(ctx, events[index:])
			return err
		}
	}
	return nil
}

func outboxRouting(event entities.OutboxEvent) (string, string, error) {
	switch event.EventType {
	case "schedule.rebuild.requested":
		var intent entities.RebuildIntent
		if err := json.Unmarshal(event.Payload, &intent); err != nil {
			return "", "", fmt.Errorf("decode outbox intent: %w", err)
		}
		return event.EventType, intent.CorrelationID, nil
	case "notification.delivery.requested":
		return event.EventType, event.ID, nil
	default:
		return "", "", fmt.Errorf("unsupported outbox event type %q", event.EventType)
	}
}

func (p OutboxPublisher) releaseClaims(ctx context.Context, events []entities.OutboxEvent) {
	for _, event := range events {
		_ = p.repository.ReleaseClaim(ctx, p.db, event.ID)
	}
}
