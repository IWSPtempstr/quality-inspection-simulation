package tests

import (
	"context"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"testing"
)

func TestG4MigrationCreatesCenterScopedBusinessTables(t *testing.T) {
	ctx := context.Background()
	container, url := startPostgres(t, ctx)
	t.Cleanup(func() { _ = container.Terminate(ctx) })
	db, err := postgres.Open(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := sqlDB.Close(); err != nil {
			t.Errorf("close database: %v", err)
		}
	})
	if err := postgres.Migrate(ctx, sqlDB, migrationsDir(t)); err != nil {
		t.Fatal(err)
	}
	for _, model := range []any{models.DetectionProject{}, models.CenterProject{}, models.Order{}, models.OrderProject{}, models.Equipment{}, models.Employee{}, models.Shift{}, models.Unavailability{}} {
		var n int64
		if err := db.Model(model).Count(&n).Error; err != nil {
			t.Fatalf("%T missing: %v", model, err)
		}
	}
}
