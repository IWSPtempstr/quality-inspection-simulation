package tests

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	postgrescontainer "github.com/testcontainers/testcontainers-go/modules/postgres"
	"gorm.io/gorm"
)

var errForceRollback = errors.New("force transaction rollback")

func TestInfrastructurePersistence(t *testing.T) {
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

	t.Run("rollback leaves all infrastructure tables empty", func(t *testing.T) {
		manager := services.NewTransactionManager(db)
		if err := manager.WithinTransaction(ctx, func(tx *gorm.DB) error {
			if err := writeInfrastructure(ctx, tx, sample("a")); err != nil {
				return err
			}
			return errForceRollback
		}); !errors.Is(err, errForceRollback) {
			t.Fatalf("transaction error = %v, want rollback sentinel", err)
		}
		assertCounts(t, db, 0, 0, 0)
	})

	t.Run("successful transaction persists all infrastructure records", func(t *testing.T) {
		manager := services.NewTransactionManager(db)
		if err := manager.WithinTransaction(ctx, func(tx *gorm.DB) error {
			return writeInfrastructure(ctx, tx, sample("b"))
		}); err != nil {
			t.Fatalf("persist infrastructure records: %v", err)
		}
		assertCounts(t, db, 1, 1, 1)

		events, err := (repositories.OutboxRepository{}).ListUnpublished(ctx, db)
		if err != nil {
			t.Fatalf("list unpublished outbox events: %v", err)
		}
		if len(events) != 1 || events[0].EventType != "schedule.preview.created" {
			t.Fatalf("unpublished events = %#v, want one persisted event", events)
		}
	})

	t.Run("idempotency key is unique within its scope", func(t *testing.T) {
		record := sample("c").idempotency
		err := services.NewTransactionManager(db).WithinTransaction(ctx, func(tx *gorm.DB) error {
			return (repositories.IdempotencyRepository{}).Create(ctx, tx, record)
		})
		if err == nil {
			t.Fatal("duplicate scoped idempotency key error = nil, want unique constraint violation")
		}
	})

	t.Run("audit logs reject update and delete", func(t *testing.T) {
		var audit models.AuditLog
		if err := db.First(&audit).Error; err != nil {
			t.Fatalf("load audit log: %v", err)
		}
		if err := db.Model(&audit).Update("action", "tampered").Error; err == nil {
			t.Fatal("audit update error = nil, want append-only trigger rejection")
		}
		if err := db.Delete(&audit).Error; err == nil {
			t.Fatal("audit delete error = nil, want append-only trigger rejection")
		}
	})
}

type infrastructureSample struct {
	idempotency entities.IdempotencyRecord
	audit       entities.AuditLog
	outbox      entities.OutboxEvent
}

func sample(suffix string) infrastructureSample {
	now := time.Date(2026, time.July, 14, 8, 0, 0, 0, time.UTC)
	return infrastructureSample{
		idempotency: entities.IdempotencyRecord{
			ID: "00000000-0000-0000-0000-00000000000" + suffix, Scope: "schedule-preview",
			IdempotencyKey: "request-key", RequestHash: "sha256:request", CreatedAt: now,
		},
		audit: entities.AuditLog{
			ID: "10000000-0000-0000-0000-00000000000" + suffix, ActorID: "scheduler-1",
			Action: "schedule_preview.created", EntityType: "schedule_preview", EntityID: "preview-1",
			RequestID: "request-1", CorrelationID: "correlation-1", Outcome: "succeeded",
			Detail: json.RawMessage(`{"source":"integration-test"}`), CreatedAt: now,
		},
		outbox: entities.OutboxEvent{
			ID: "20000000-0000-0000-0000-00000000000" + suffix, EventType: "schedule.preview.created",
			AggregateType: "schedule_preview", AggregateID: "preview-1",
			Payload: json.RawMessage(`{"preview_id":"preview-1"}`), OccurredAt: now, CreatedAt: now,
		},
	}
}

func writeInfrastructure(ctx context.Context, tx *gorm.DB, value infrastructureSample) error {
	if err := (repositories.IdempotencyRepository{}).Create(ctx, tx, value.idempotency); err != nil {
		return err
	}
	if err := (repositories.AuditLogRepository{}).Append(ctx, tx, value.audit); err != nil {
		return err
	}
	return (repositories.OutboxRepository{}).Enqueue(ctx, tx, value.outbox)
}

func assertCounts(t *testing.T, db *gorm.DB, idempotency, audit, outbox int64) {
	t.Helper()
	for _, assertion := range []struct {
		model any
		want  int64
	}{
		{models.IdempotencyRecord{}, idempotency},
		{models.AuditLog{}, audit},
		{models.OutboxEvent{}, outbox},
	} {
		var count int64
		if err := db.Model(assertion.model).Count(&count).Error; err != nil {
			t.Fatalf("count %T: %v", assertion.model, err)
		}
		if count != assertion.want {
			t.Fatalf("count %T = %d, want %d", assertion.model, count, assertion.want)
		}
	}
}

func startPostgres(t *testing.T, ctx context.Context) (*postgrescontainer.PostgresContainer, string) {
	t.Helper()
	container, err := postgrescontainer.Run(ctx,
		"postgres:16-alpine",
		postgrescontainer.WithDatabase("detection_center"),
		postgrescontainer.WithUsername("postgres"),
		postgrescontainer.WithPassword("postgres"),
		postgrescontainer.BasicWaitStrategies(),
	)
	if err != nil {
		t.Fatalf("start PostgreSQL testcontainer: %v", err)
	}
	databaseURL, err := container.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		_ = container.Terminate(ctx)
		t.Fatalf("get PostgreSQL container URL: %v", err)
	}
	return container, databaseURL
}

func migrationsDir(t *testing.T) string {
	t.Helper()
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("locate test source")
	}
	path := filepath.Join(filepath.Dir(filename), "..", "migrations")
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("stat migrations directory: %v", err)
	}
	return path
}
