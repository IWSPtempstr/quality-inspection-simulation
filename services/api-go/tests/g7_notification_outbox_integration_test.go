package tests

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"gorm.io/gorm"
)

func TestNotificationOutboxPublishesConfirmedPayloadBeforeMarkingPublished(t *testing.T) {
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

	payload := json.RawMessage(`{"center_id":"center-a","notification_id":"note-1","channel":"in_app"}`)
	event := entities.OutboxEvent{ID: "00000000-0000-0000-0000-000000000701", EventType: "notification.delivery.requested", AggregateType: "notification", AggregateID: "00000000-0000-0000-0000-000000000702", Payload: payload, OccurredAt: time.Now().UTC(), CreatedAt: time.Now().UTC()}
	if err := db.Transaction(func(tx *gorm.DB) error { return (repositories.OutboxRepository{}).Enqueue(ctx, tx, event) }); err != nil {
		t.Fatalf("enqueue notification outbox: %v", err)
	}
	publisher := &capturingPublisher{}
	if err := services.NewOutboxPublisher(db, publisher).PublishPending(ctx, 10); err != nil {
		t.Fatalf("publish notification outbox: %v", err)
	}
	if publisher.routingKey != "notification.delivery.requested" || publisher.correlationID != event.ID {
		t.Fatalf("publish = routing=%q correlation=%q", publisher.routingKey, publisher.correlationID)
	}
	if !jsonEqual(t, publisher.payload, payload) {
		t.Fatalf("publish payload = %s, want %s", publisher.payload, payload)
	}
	var stored struct{ PublishedAt *time.Time }
	if err := db.Table("outbox_events").Select("published_at").Where("id = ?", event.ID).Scan(&stored).Error; err != nil {
		t.Fatalf("load published outbox: %v", err)
	}
	if stored.PublishedAt == nil {
		t.Fatal("notification outbox was not marked published after confirmation")
	}
}

func TestNotificationDeliveryPersistsFailureThenRetrySuccess(t *testing.T) {
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

	now := time.Now().UTC()
	notificationID := "00000000-0000-0000-0000-000000000703"
	if err := db.Exec(`INSERT INTO notifications (id, center_id, recipient_id, title, body, channel, status, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`, notificationID, "center-a", "recipient-a", "Execution exception", "A step failed.", "webhook_stub", "pending", 1, now, now).Error; err != nil {
		t.Fatalf("seed notification: %v", err)
	}
	if err := db.Exec(`INSERT INTO notification_deliveries (id, notification_id, channel, status, attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)`, "00000000-0000-0000-0000-000000000704", notificationID, "webhook_stub", "pending", 0, now, now).Error; err != nil {
		t.Fatalf("seed delivery: %v", err)
	}
	payload := json.RawMessage(`{"center_id":"center-a","notification_id":"00000000-0000-0000-0000-000000000703","channel":"webhook_stub"}`)
	worker := services.NewNotificationDeliveryWorker(db, failingNotificationChannel{})
	if err := worker.Process(ctx, payload); err == nil {
		t.Fatal("failed webhook delivery error = nil")
	}
	if err := worker.MarkFailed(ctx, payload, "stub unavailable"); err != nil {
		t.Fatalf("persist failed delivery: %v", err)
	}
	assertNotificationDelivery(t, db, notificationID, "failed", 1)

	worker = services.NewNotificationDeliveryWorker(db, successfulNotificationChannel{})
	if err := worker.Process(ctx, payload); err != nil {
		t.Fatalf("retry delivery: %v", err)
	}
	assertNotificationDelivery(t, db, notificationID, "sent", 2)
}

type failingNotificationChannel struct{}

func (failingNotificationChannel) Deliver(context.Context, string, json.RawMessage) error {
	return errors.New("webhook stub unavailable")
}

type successfulNotificationChannel struct{}

func (successfulNotificationChannel) Deliver(context.Context, string, json.RawMessage) error {
	return nil
}

func assertNotificationDelivery(t *testing.T, db *gorm.DB, notificationID, wantStatus string, wantAttempts int) {
	t.Helper()
	var got struct {
		Status   string
		Attempts int
	}
	if err := db.Table("notification_deliveries").Select("status, attempts").Where("notification_id = ?", notificationID).Scan(&got).Error; err != nil {
		t.Fatalf("load notification delivery: %v", err)
	}
	if got.Status != wantStatus || got.Attempts != wantAttempts {
		t.Fatalf("notification delivery = (%q, %d), want (%q, %d)", got.Status, got.Attempts, wantStatus, wantAttempts)
	}
}

func jsonEqual(t *testing.T, got, want []byte) bool {
	t.Helper()
	var gotValue, wantValue any
	return json.Unmarshal(got, &gotValue) == nil && json.Unmarshal(want, &wantValue) == nil && reflect.DeepEqual(gotValue, wantValue)
}

type capturingPublisher struct {
	routingKey, correlationID string
	payload                   []byte
}

func (p *capturingPublisher) PublishConfirmed(_ context.Context, routingKey string, payload []byte, correlationID string) error {
	p.routingKey, p.correlationID = routingKey, correlationID
	p.payload = append([]byte(nil), payload...)
	return nil
}
