package services

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

type IdempotencyService struct {
	repository repositories.IdempotencyRepository
}

func (service IdempotencyService) Register(ctx context.Context, tx *gorm.DB, scope, key string, requestBody []byte) error {
	hash := requestHash(requestBody)
	claimed, err := service.repository.CreateIfAbsent(ctx, tx, entities.IdempotencyRecord{
		ID: uuid.NewString(), Scope: scope, IdempotencyKey: key, RequestHash: hash, CreatedAt: time.Now().UTC(),
	})
	if err != nil {
		return err
	}
	if claimed {
		return nil
	}
	record, found, err := service.repository.Find(ctx, tx, scope, key)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("idempotency record disappeared after conflict")
	}
	if record.RequestHash == hash {
		return entities.ErrIdempotencyReplay
	}
	return entities.ErrIdempotencyConflict
}

func RequireVersion(expected, current int64) error {
	if expected != current {
		return fmt.Errorf("%w: expected %d, current %d", entities.ErrVersionConflict, expected, current)
	}
	return nil
}

type AuditService struct {
	repository repositories.AuditLogRepository
}

type AuditEntry struct {
	Actor         entities.Actor
	Action        string
	EntityType    string
	EntityID      string
	RequestID     string
	CorrelationID string
	BeforeVersion *int64
	AfterVersion  *int64
	Outcome       string
	Detail        []byte
}

func (service AuditService) Append(ctx context.Context, tx *gorm.DB, entry AuditEntry) error {
	return service.repository.Append(ctx, tx, entities.AuditLog{
		ID: uuid.NewString(), ActorID: entry.Actor.ID, Action: entry.Action, EntityType: entry.EntityType,
		EntityID: entry.EntityID, RequestID: entry.RequestID, CorrelationID: entry.CorrelationID,
		BeforeVersion: entry.BeforeVersion, AfterVersion: entry.AfterVersion, Outcome: entry.Outcome,
		Detail: entry.Detail, CreatedAt: time.Now().UTC(),
	})
}

func requestHash(body []byte) string {
	sum := sha256.Sum256(body)
	return "sha256:" + hex.EncodeToString(sum[:])
}
