package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"os"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/rabbitmq"
	redisclient "github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/redis"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/conf"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/core"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/rabbitmq/amqp091-go"
)

func main() {
	config, err := conf.Load(os.LookupEnv)
	if err != nil {
		slog.Error("invalid configuration", "error", err)
		os.Exit(1)
	}

	logger := core.NewLogger(config.Environment)
	ctx := context.Background()
	db, err := postgres.Open(ctx, config.DatabaseURL)
	if err != nil {
		logger.Error("initialize PostgreSQL", "error", err)
		os.Exit(1)
	}
	sqlDB, err := db.DB()
	if err != nil {
		logger.Error("access PostgreSQL", "error", err)
		os.Exit(1)
	}
	defer func() { _ = sqlDB.Close() }()
	debouncer, err := redisclient.Open(config.RedisURL)
	if err != nil {
		logger.Error("initialize Redis", "error", err)
		os.Exit(1)
	}
	defer func() { _ = debouncer.Close() }()
	broker, err := rabbitmq.Open(config.RabbitMQURL)
	if err != nil {
		logger.Error("initialize RabbitMQ", "error", err)
		os.Exit(1)
	}
	defer func() { _ = broker.Close() }()
	deliveries, err := broker.Deliveries()
	if err != nil {
		logger.Error("consume RabbitMQ", "error", err)
		os.Exit(1)
	}
	notificationDeliveries, err := broker.NotificationDeliveries()
	if err != nil {
		logger.Error("consume notification RabbitMQ", "error", err)
		os.Exit(1)
	}
	processor := services.NewResourceEventService(db, debouncer)
	publisher := services.NewOutboxPublisher(db, broker)
	writeback := services.NewScheduleWritebackWorker(db, services.HTTPPartnerClient{BaseURL: config.PartnerScheduleURL, Credential: config.PartnerScheduleCredential})
	notifier := services.NewNotificationDeliveryWorker(db, services.HTTPNotificationChannel{BaseURL: config.NotificationWebhookURL, Credential: config.NotificationWebhookCredential})
	go publishPendingPeriodically(ctx, publisher, 5*time.Second)
	go publishScheduleWritebacks(ctx, writeback, 5*time.Second)
	go consumeNotificationDeliveries(ctx, logger, broker, notificationDeliveries, notifier)
	logger.Info("worker started", "mode", "g5-resource-events")
	for delivery := range deliveries {
		ack, processErr := processor.Process(ctx, delivery.Body, delivery.CorrelationId)
		if processErr == nil && ack {
			if err := delivery.Ack(false); err != nil {
				logger.Error("ack delivery", "error", err)
			}
			_ = publisher.PublishPending(ctx, 50)
			continue
		}
		if errors.Is(processErr, services.ErrRetryableResourceEvent) {
			retry, err := processor.RecordRetry(ctx, delivery.Body)
			if err != nil {
				// The retry count is part of the durable Inbox state. If it cannot be
				// recorded, leave the delivery unacknowledged for broker redelivery.
				if nackErr := delivery.Nack(false, true); nackErr != nil {
					logger.Error("requeue delivery after retry persistence failure", "error", nackErr)
				}
				logger.Error("persist resource-event retry", "error", err)
				continue
			}
			if err := broker.Retry(delivery, retry-1, processErr.Error()); err != nil {
				logger.Error("retry delivery", "error", err)
			}
			continue
		}
		if err := broker.Quarantine(delivery, errorText(processErr)); err != nil {
			logger.Error("quarantine delivery", "error", err)
		}
	}
	if err := core.WaitForShutdown(); err != nil {
		logger.Error("worker stopped unexpectedly", "error", err)
		os.Exit(1)
	}
}

type notificationBroker interface {
	RetryNotification(amqp091.Delivery, int, string) (bool, error)
}

type notificationProcessor interface {
	Process(context.Context, json.RawMessage) error
	MarkFailed(context.Context, json.RawMessage, string) error
}

func consumeNotificationDeliveries(ctx context.Context, logger *slog.Logger, broker notificationBroker, deliveries <-chan amqp091.Delivery, processor notificationProcessor) {
	for delivery := range deliveries {
		if err := processor.Process(ctx, delivery.Body); err == nil {
			if ackErr := delivery.Ack(false); ackErr != nil {
				logger.Error("ack notification delivery", "error", ackErr)
			}
			continue
		} else if persistErr := processor.MarkFailed(ctx, delivery.Body, errorText(err)); persistErr != nil {
			if nackErr := delivery.Nack(false, true); nackErr != nil {
				logger.Error("requeue notification delivery after failure persistence error", "error", nackErr)
			}
			logger.Error("persist notification delivery failure", "error", persistErr)
			continue
		} else if _, retryErr := broker.RetryNotification(delivery, notificationRetryCount(delivery), errorText(err)); retryErr != nil {
			logger.Error("retry notification delivery", "error", retryErr)
		}
	}
}

func notificationRetryCount(delivery amqp091.Delivery) int {
	value, ok := delivery.Headers["x-g7-retry-count"]
	if !ok {
		return 0
	}
	switch retry := value.(type) {
	case int:
		return retry
	case int32:
		return int(retry)
	case int64:
		return int(retry)
	default:
		return 0
	}
}

type pendingScheduleWriteback interface {
	PublishPending(context.Context, int) error
}

func publishScheduleWritebacks(ctx context.Context, publisher pendingScheduleWriteback, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		if err := publisher.PublishPending(ctx, 50); err != nil {
			slog.Error("publish schedule writebacks", "error", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

type pendingOutboxPublisher interface {
	PublishPending(context.Context, int) error
}

// publishPendingPeriodically recovers unpublished intents after a broker outage
// even when no later resource delivery reaches the worker.
func publishPendingPeriodically(ctx context.Context, publisher pendingOutboxPublisher, interval time.Duration) {
	publish := func() {
		if err := publisher.PublishPending(ctx, 50); err != nil {
			slog.Error("publish pending outbox events", "error", err)
		}
	}
	publish()
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			publish()
		}
	}
}

func errorText(err error) string {
	if err == nil {
		return "processing failed"
	}
	return err.Error()
}
