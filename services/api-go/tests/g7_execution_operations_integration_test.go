package tests

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/rabbitmq"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/google/uuid"
	"github.com/rabbitmq/amqp091-go"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
	"gorm.io/gorm"
)

func TestG7ExecutionEventsNotificationsAndDeliveryRecovery(t *testing.T) {
	ctx, db := g6RepairDatabase(t)
	center := "center-g7"
	orderID := uuid.NewString()
	stepID := uuid.NewString()
	seedG7OrderAndStep(t, db, center, orderID, stepID)
	if err := db.Exec("INSERT INTO center_scheduler_users (center_id, user_id) VALUES (?, ?), (?, ?), (?, ?)", center, "creator-g7", center, "scheduler-g7", "other-center", "scheduler-g7").Error; err != nil {
		t.Fatalf("seed scheduler recipients: %v", err)
	}

	service := services.NewExecutionService(db)
	actor := entities.Actor{ID: "scheduler-g7", CenterID: center, Roles: []entities.Role{entities.RoleScheduler}}

	t.Run("one concurrent start wins and rejected completion rolls back", func(t *testing.T) {
		start := make(chan struct{})
		results := make(chan error, 2)
		var group sync.WaitGroup
		for range 2 {
			group.Add(1)
			go func() {
				defer group.Done()
				<-start
				_, err := service.Start(ctx, actor, stepID, 1)
				results <- err
			}()
		}
		close(start)
		group.Wait()
		close(results)
		successes := 0
		for err := range results {
			if err == nil {
				successes++
			}
		}
		if successes != 1 {
			t.Fatalf("concurrent starts succeeded %d times, want exactly one", successes)
		}

		var step models.ScheduleStep
		if err := db.First(&step, "id = ?", stepID).Error; err != nil {
			t.Fatalf("load started step: %v", err)
		}
		if step.Status != "running" || step.Version != 2 || step.ExecutorID == nil || *step.ExecutorID != actor.ID || step.ActualStartedAt == nil {
			t.Fatalf("started step = %#v, want running version 2 with executor and timestamp", step)
		}
		var beforeOutbox int64
		if err := db.Model(&models.OutboxEvent{}).Count(&beforeOutbox).Error; err != nil {
			t.Fatalf("count outbox before invalid completion: %v", err)
		}
		if _, err := service.Complete(ctx, actor, stepID, 1, json.RawMessage(`{"result":"ok"}`)); !errors.Is(err, entities.ErrVersionConflict) {
			t.Fatalf("stale complete error = %v, want version conflict", err)
		}
		var after models.ScheduleStep
		if err := db.First(&after, "id = ?", stepID).Error; err != nil {
			t.Fatalf("reload step after rollback: %v", err)
		}
		if after.Status != "running" || after.Version != 2 || after.ActualCompletedAt != nil {
			t.Fatalf("stale completion mutated step = %#v", after)
		}
		var afterOutbox int64
		if err := db.Model(&models.OutboxEvent{}).Count(&afterOutbox).Error; err != nil {
			t.Fatalf("count outbox after invalid completion: %v", err)
		}
		if afterOutbox != beforeOutbox {
			t.Fatalf("invalid completion emitted outbox rows: before=%d after=%d", beforeOutbox, afterOutbox)
		}
	})

	t.Run("events support acknowledge and direct close with center isolation", func(t *testing.T) {
		ackEvent, err := service.CreateExecutionEvent(ctx, center, "execution.anomaly", "schedule_step", "warning", stepID, json.RawMessage(`{"reason":"fixture"}`))
		if err != nil {
			t.Fatalf("create acknowledgement event: %v", err)
		}
		acknowledged, err := service.AcknowledgeEvent(ctx, actor, ackEvent.ID, ackEvent.Version)
		if err != nil || acknowledged.Status != "acknowledged" || acknowledged.AcknowledgedBy == nil || *acknowledged.AcknowledgedBy != actor.ID {
			t.Fatalf("acknowledge event = (%#v, %v)", acknowledged, err)
		}
		closeEvent, err := service.CreateExecutionEvent(ctx, center, "partner.anomaly", "order", "error", orderID, json.RawMessage(`{"reason":"fixture"}`))
		if err != nil {
			t.Fatalf("create close event: %v", err)
		}
		closed, err := service.CloseEvent(ctx, actor, closeEvent.ID, closeEvent.Version, "handled")
		if err != nil || closed.Status != "closed" || closed.Disposition == nil || *closed.Disposition != "handled" || closed.ClosedBy == nil || *closed.ClosedBy != actor.ID {
			t.Fatalf("direct close event = (%#v, %v)", closed, err)
		}
		other := entities.Actor{ID: "scheduler-g7", CenterID: "other-center", Roles: []entities.Role{entities.RoleScheduler}}
		if _, err := service.Event(ctx, other, closeEvent.ID); err == nil {
			t.Fatal("other center loaded event, want isolation")
		}
	})

	t.Run("recipient set is center scoped, deduplicated, and reads are idempotent", func(t *testing.T) {
		var notifications []models.Notification
		if err := db.Where("center_id = ?", center).Find(&notifications).Error; err != nil {
			t.Fatalf("list notifications: %v", err)
		}
		recipients := map[string]struct{}{}
		for _, notification := range notifications {
			recipients[notification.RecipientID] = struct{}{}
			if notification.RecipientID == "scheduler-g7" && notification.CenterID != center {
				t.Fatalf("cross-center notification = %#v", notification)
			}
		}
		if _, found := recipients["creator-g7"]; !found {
			t.Fatalf("creator did not receive notification: %#v", recipients)
		}
		if _, found := recipients["scheduler-g7"]; !found {
			t.Fatalf("center scheduler did not receive notification: %#v", recipients)
		}
		if _, found := recipients["scheduler-other"]; found {
			t.Fatalf("other-center scheduler received notification: %#v", recipients)
		}
		var mine models.Notification
		if err := db.Where("center_id = ? AND recipient_id = ?", center, actor.ID).First(&mine).Error; err != nil {
			t.Fatalf("load recipient notification: %v", err)
		}
		if err := service.MarkRead(ctx, actor, mine.ID); err != nil {
			t.Fatalf("first read: %v", err)
		}
		var once models.Notification
		if err := db.First(&once, "id = ?", mine.ID).Error; err != nil || once.ReadAt == nil {
			t.Fatalf("load first read = (%#v, %v)", once, err)
		}
		firstRead := *once.ReadAt
		if err := service.MarkRead(ctx, actor, mine.ID); err != nil {
			t.Fatalf("repeat read: %v", err)
		}
		var twice models.Notification
		if err := db.First(&twice, "id = ?", mine.ID).Error; err != nil || twice.ReadAt == nil || !twice.ReadAt.Equal(firstRead) {
			t.Fatalf("repeat read changed persisted marker = (%#v, %v)", twice, err)
		}
	})

	t.Run("failed delivery remains pending until failure is persisted and can recover", func(t *testing.T) {
		notificationID := uuid.NewString()
		now := time.Now().UTC()
		if err := db.Create(&models.Notification{ID: notificationID, CenterID: center, RecipientID: actor.ID, Title: "fixture", Body: "fixture", Channel: "webhook_stub", Status: "pending", Version: 1, CreatedAt: now, UpdatedAt: now}).Error; err != nil {
			t.Fatalf("create notification: %v", err)
		}
		if err := db.Create(&models.NotificationDelivery{ID: uuid.NewString(), NotificationID: notificationID, Channel: "webhook_stub", Status: "pending", CreatedAt: now, UpdatedAt: now}).Error; err != nil {
			t.Fatalf("create delivery: %v", err)
		}
		event := entities.OutboxEvent{ID: uuid.NewString(), EventType: "notification.delivery.requested", AggregateType: "notification", AggregateID: notificationID, Payload: json.RawMessage(fmt.Sprintf(`{"notification_id":%q,"channel":"webhook_stub"}`, notificationID)), OccurredAt: now, CreatedAt: now}
		failed := services.NewNotificationDeliveryWorker(db, notificationChannelFunc(func(context.Context, string, json.RawMessage) error { return errors.New("stub unavailable") }))
		if err := failed.Process(ctx, event.Payload); err == nil {
			t.Fatal("failed webhook delivery error = nil")
		}
		assertG7DeliveryStatus(t, db, notificationID, "pending", "pending")
		if err := failed.MarkFailed(ctx, event.Payload, "stub unavailable"); err != nil {
			t.Fatalf("persist final delivery failure: %v", err)
		}
		assertG7DeliveryStatus(t, db, notificationID, "failed", "failed")
		recovered := services.NewNotificationDeliveryWorker(db, notificationChannelFunc(func(context.Context, string, json.RawMessage) error { return nil }))
		if err := recovered.Process(ctx, event.Payload); err != nil {
			t.Fatalf("recovered webhook delivery: %v", err)
		}
		assertG7DeliveryStatus(t, db, notificationID, "sent", "sent")
	})
}

func TestG7NotificationRabbitRetryAndDLQ(t *testing.T) {
	ctx := context.Background()
	container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{ContainerRequest: testcontainers.ContainerRequest{Image: "rabbitmq:4-alpine", ExposedPorts: []string{"5672/tcp"}, WaitingFor: wait.ForAll(wait.ForListeningPort("5672/tcp"), wait.ForLog("Server startup complete")).WithDeadline(90 * time.Second)}, Started: true})
	if err != nil {
		t.Fatalf("start RabbitMQ: %v", err)
	}
	t.Cleanup(func() { _ = container.Terminate(ctx) })
	host, err := container.Host(ctx)
	if err != nil {
		t.Fatalf("RabbitMQ host: %v", err)
	}
	port, err := container.MappedPort(ctx, "5672/tcp")
	if err != nil {
		t.Fatalf("RabbitMQ port: %v", err)
	}
	url := fmt.Sprintf("amqp://guest:guest@%s:%s/", host, port.Port())
	client, err := rabbitmq.Open(url)
	if err != nil {
		t.Fatalf("open G7 RabbitMQ client: %v", err)
	}
	t.Cleanup(func() { _ = client.Close() })

	inspect, err := amqp091.Dial(url)
	if err != nil {
		t.Fatalf("open inspection connection: %v", err)
	}
	t.Cleanup(func() { _ = inspect.Close() })
	channel, err := inspect.Channel()
	if err != nil {
		t.Fatalf("open inspection channel: %v", err)
	}
	t.Cleanup(func() { _ = channel.Close() })
	deliveries, err := client.NotificationDeliveries()
	if err != nil {
		t.Fatalf("consume notification queue: %v", err)
	}
	publish := func(id string) {
		t.Helper()
		if err := channel.PublishWithContext(ctx, rabbitmq.InternalExchange, "notification.delivery.requested", false, false, amqp091.Publishing{Body: []byte(fmt.Sprintf(`{"notification_id":%q,"channel":"webhook_stub"}`, id)), CorrelationId: "correlation-" + id, DeliveryMode: amqp091.Persistent}); err != nil {
			t.Fatalf("publish notification: %v", err)
		}
	}
	next := func() amqp091.Delivery {
		t.Helper()
		select {
		case delivery := <-deliveries:
			return delivery
		case <-time.After(15 * time.Second):
			t.Fatal("timed out waiting for notification delivery")
			return amqp091.Delivery{}
		}
	}
	publish("retry")
	if acked, err := client.RetryNotification(next(), 0, "stub unavailable"); err != nil || acked {
		t.Fatalf("first notification retry = (acked=%v, err=%v), want (false, nil)", acked, err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for {
		state, inspectErr := channel.QueueDeclarePassive("api-go.g7.notification.retry.1m", true, false, false, false, nil)
		if inspectErr != nil {
			t.Fatalf("inspect notification retry queue: %v", inspectErr)
		}
		if state.Messages == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("notification retry queue messages = %d, want one durable message", state.Messages)
		}
		time.Sleep(25 * time.Millisecond)
	}

	publish("dlq")
	if acked, err := client.RetryNotification(next(), 3, "final failure"); err != nil || !acked {
		t.Fatalf("final notification retry = (acked=%v, err=%v), want (true, nil)", acked, err)
	}
	dlq, err := channel.Consume("api-go.g7.notification.dlq", "", true, false, false, false, nil)
	if err != nil {
		t.Fatalf("consume notification DLQ: %v", err)
	}
	select {
	case delivery := <-dlq:
		var wrapper struct {
			Envelope      json.RawMessage `json:"envelope"`
			FailureReason string          `json:"failure_reason"`
		}
		if err := json.Unmarshal(delivery.Body, &wrapper); err != nil || wrapper.FailureReason != "final failure" {
			t.Fatalf("notification DLQ wrapper = (%#v, %v)", wrapper, err)
		}
	case <-time.After(15 * time.Second):
		t.Fatal("timed out waiting for notification DLQ")
	}
}

type notificationChannelFunc func(context.Context, string, json.RawMessage) error

func (fn notificationChannelFunc) Deliver(ctx context.Context, notificationID string, payload json.RawMessage) error {
	return fn(ctx, notificationID, payload)
}

func seedG7OrderAndStep(t *testing.T, db *gorm.DB, center, orderID, stepID string) {
	t.Helper()
	now := time.Now().UTC()
	if err := db.Create(&models.Order{ID: orderID, CenterID: center, SampleName: "G7 fixture", SampleQuantity: 1, CertificationType: "CCC", Priority: "normal", PromisedFinishTime: now.Add(24 * time.Hour), Status: "scheduled", Version: 1, CreatedBy: "creator-g7", UpdatedBy: "creator-g7", CreatedAt: now, UpdatedAt: now}).Error; err != nil {
		t.Fatalf("seed G7 order: %v", err)
	}
	if err := db.Create(&models.ScheduleStep{ID: stepID, CenterID: center, ScheduleVersion: 1, OrderID: orderID, ProjectID: uuid.NewString(), EmployeeIDs: []byte("[]"), StartsAt: now.Add(3 * time.Hour), EndsAt: now.Add(4 * time.Hour), Status: "scheduled", Version: 1, CreatedAt: now, UpdatedAt: now}).Error; err != nil {
		t.Fatalf("seed G7 schedule step: %v", err)
	}
}

func assertG7DeliveryStatus(t *testing.T, db *gorm.DB, notificationID, notificationStatus, deliveryStatus string) {
	t.Helper()
	var notification models.Notification
	if err := db.First(&notification, "id = ?", notificationID).Error; err != nil {
		t.Fatalf("load notification: %v", err)
	}
	var delivery models.NotificationDelivery
	if err := db.Where("notification_id = ? AND channel = ?", notificationID, "webhook_stub").First(&delivery).Error; err != nil {
		t.Fatalf("load notification delivery: %v", err)
	}
	if notification.Status != notificationStatus || delivery.Status != deliveryStatus {
		t.Fatalf("notification delivery statuses = notification=%q delivery=%q, want notification=%q delivery=%q", notification.Status, delivery.Status, notificationStatus, deliveryStatus)
	}
}
