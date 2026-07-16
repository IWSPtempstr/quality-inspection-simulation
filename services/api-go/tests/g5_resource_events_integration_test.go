package tests

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"gorm.io/gorm"
)

func TestResourceEventsRecoverReceivedInboxAndPreserveProjectionRules(t *testing.T) {
	ctx := context.Background()
	container, databaseURL := startPostgres(t, ctx)
	t.Cleanup(func() { _ = container.Terminate(ctx) })
	db, err := postgres.Open(ctx, databaseURL)
	if err != nil {
		t.Fatalf("open PostgreSQL: %v", err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatalf("get SQL database: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })
	if err := postgres.Migrate(ctx, sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("migrate PostgreSQL: %v", err)
	}

	debouncer := &testDebouncer{failures: 1}
	processor := services.NewResourceEventService(db, debouncer)
	first := resourceEventJSON(t, "event-1", "center-a", "equipment-a", 2)
	if ack, err := processor.Process(ctx, first, "correlation-1"); ack || !errors.Is(err, services.ErrRetryableResourceEvent) {
		t.Fatalf("Redis outage Process() = (%v, %v), want retryable unacknowledged", ack, err)
	}
	assertInboxStatus(t, db, "event-1", entities.InboxReceived, 0)
	assertG5Counts(t, db, 0, 0)
	if retry, err := processor.RecordRetry(ctx, first); err != nil || retry != 1 {
		t.Fatalf("RecordRetry() = (%d, %v), want (1, nil)", retry, err)
	}
	assertInboxStatus(t, db, "event-1", entities.InboxReceived, 1)

	if ack, err := processor.Process(ctx, first, "correlation-1"); !ack || err != nil {
		t.Fatalf("redelivered received event Process() = (%v, %v), want acknowledged success", ack, err)
	}
	assertInboxStatus(t, db, "event-1", entities.InboxProcessed, 1)
	assertG5Counts(t, db, 1, 1)

	if ack, err := processor.Process(ctx, first, "correlation-1"); !ack || err != nil {
		t.Fatalf("processed duplicate Process() = (%v, %v), want acknowledged duplicate", ack, err)
	}
	assertG5Counts(t, db, 1, 1)

	stale := resourceEventJSON(t, "event-stale", "center-a", "equipment-a", 1)
	if ack, err := processor.Process(ctx, stale, "correlation-stale"); !ack || err != nil {
		t.Fatalf("stale event Process() = (%v, %v), want acknowledged stale event", ack, err)
	}
	assertInboxStatus(t, db, "event-stale", entities.InboxStale, 0)
	assertG5Counts(t, db, 1, 1)

	otherCenter := resourceEventJSON(t, "event-center-b", "center-b", "equipment-a", 1)
	if ack, err := processor.Process(ctx, otherCenter, "correlation-center-b"); !ack || err != nil {
		t.Fatalf("other center Process() = (%v, %v), want acknowledged success", ack, err)
	}
	assertG5Counts(t, db, 2, 2)

	publisher := &testPublisher{failures: 1}
	outbox := services.NewOutboxPublisher(db, publisher)
	if err := outbox.PublishPending(ctx, 10); err == nil {
		t.Fatal("first outbox publish error = nil, want confirmation failure")
	}
	var unpublished models.OutboxEvent
	if err := db.Where("published_at IS NULL").First(&unpublished).Error; err != nil {
		t.Fatalf("load released outbox event: %v", err)
	}
	if unpublished.ClaimedAt != nil {
		t.Fatalf("failed publish claimed_at = %v, want nil", unpublished.ClaimedAt)
	}
	if err := outbox.PublishPending(ctx, 10); err != nil {
		t.Fatalf("recovered outbox publish: %v", err)
	}
	var remaining int64
	if err := db.Model(&models.OutboxEvent{}).Where("published_at IS NULL").Count(&remaining).Error; err != nil {
		t.Fatalf("count unpublished outbox events: %v", err)
	}
	if remaining != 0 {
		t.Fatalf("unpublished outbox events = %d, want 0", remaining)
	}
}

type testDebouncer struct{ failures int }

func (d *testDebouncer) SetFirst(context.Context, string, time.Duration) (bool, error) {
	if d.failures > 0 {
		d.failures--
		return false, errors.New("Redis unavailable")
	}
	return true, nil
}

type testPublisher struct{ failures int }

func (p *testPublisher) PublishConfirmed(context.Context, string, []byte, string) error {
	if p.failures > 0 {
		p.failures--
		return errors.New("broker confirmation failed")
	}
	return nil
}

func resourceEventJSON(t *testing.T, eventID, centerID, equipmentID string, version int64) []byte {
	t.Helper()
	payload, err := json.Marshal(map[string]any{
		"event_id": eventID, "center_id": centerID, "event_type": "upserted", "entity_type": "equipment", "entity_id": equipmentID,
		"source_version": version, "occurred_at": "2026-07-15T08:00:00Z", "payload": map[string]any{"name": "Line 1", "status": "available", "capacity": 1},
	})
	if err != nil {
		t.Fatalf("marshal resource event: %v", err)
	}
	return payload
}

func assertInboxStatus(t *testing.T, db *gorm.DB, eventID, status string, retryCount int) {
	t.Helper()
	var inbox models.InboxEvent
	if err := db.First(&inbox, "event_id = ?", eventID).Error; err != nil {
		t.Fatalf("load inbox event %s: %v", eventID, err)
	}
	if inbox.Status != status || inbox.RetryCount != retryCount {
		t.Fatalf("inbox %s = status %q retry %d, want status %q retry %d", eventID, inbox.Status, inbox.RetryCount, status, retryCount)
	}
}

func assertG5Counts(t *testing.T, db *gorm.DB, equipment, outbox int64) {
	t.Helper()
	for _, check := range []struct {
		model any
		want  int64
	}{{models.Equipment{}, equipment}, {models.OutboxEvent{}, outbox}} {
		var got int64
		if err := db.Model(check.model).Count(&got).Error; err != nil {
			t.Fatalf("count %T: %v", check.model, err)
		}
		if got != check.want {
			t.Fatalf("count %T = %d, want %d", check.model, got, check.want)
		}
	}
}
