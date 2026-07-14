package tests

import (
	"context"
	"errors"
	"testing"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"gorm.io/gorm"
)

func TestWriteControlsPersistAuditAndRejectDuplicateRequests(t *testing.T) {
	ctx := context.Background()
	container, databaseURL := startPostgres(t, ctx)
	t.Cleanup(func() { _ = container.Terminate(ctx) })

	db, err := postgres.Open(ctx, databaseURL)
	if err != nil {
		t.Fatalf("open container database: %v", err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatalf("get SQL database: %v", err)
	}
	defer func() { _ = sqlDB.Close() }()
	if err := postgres.Migrate(ctx, sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run Goose migrations: %v", err)
	}

	requestBody := []byte(`{"priority":"urgent"}`)
	actor := entities.Actor{ID: "scheduler-001", CenterID: "center-a", Roles: []entities.Role{entities.RoleScheduler}}
	manager := services.NewTransactionManager(db)
	idempotency := services.IdempotencyService{}
	audit := services.AuditService{}

	if err := manager.WithinTransaction(ctx, func(tx *gorm.DB) error {
		if err := idempotency.Register(ctx, tx, "order:ORD-001", "operation-001", requestBody); err != nil {
			return err
		}
		return audit.Append(ctx, tx, services.AuditEntry{
			Actor: actor, Action: "order.updated", EntityType: "order", EntityID: "ORD-001",
			RequestID: "request-001", CorrelationID: "correlation-001", Outcome: "succeeded",
			Detail: []byte(`{"changed_fields":["priority"]}`),
		})
	}); err != nil {
		t.Fatalf("persist write controls: %v", err)
	}

	if err := manager.WithinTransaction(ctx, func(tx *gorm.DB) error {
		return idempotency.Register(ctx, tx, "order:ORD-001", "operation-001", requestBody)
	}); !errors.Is(err, entities.ErrIdempotencyReplay) {
		t.Fatalf("same request error = %v, want idempotency replay", err)
	}
	if err := manager.WithinTransaction(ctx, func(tx *gorm.DB) error {
		return idempotency.Register(ctx, tx, "order:ORD-001", "operation-001", []byte(`{"priority":"vip"}`))
	}); !errors.Is(err, entities.ErrIdempotencyConflict) {
		t.Fatalf("different request error = %v, want idempotency conflict", err)
	}
	if err := services.RequireVersion(5, 4); !errors.Is(err, entities.ErrVersionConflict) {
		t.Fatalf("version mismatch error = %v, want version conflict", err)
	}

	var record models.AuditLog
	if err := db.First(&record).Error; err != nil {
		t.Fatalf("load persisted audit: %v", err)
	}
	if record.ActorID != actor.ID || record.RequestID != "request-001" || record.CorrelationID != "correlation-001" {
		t.Fatalf("audit record = %#v, want actor and request correlation", record)
	}
}
