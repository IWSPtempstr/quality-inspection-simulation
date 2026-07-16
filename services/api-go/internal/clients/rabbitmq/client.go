package rabbitmq

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/rabbitmq/amqp091-go"
)

const (
	PartnerExchange   = "partner.events"
	InternalExchange  = "internal.events"
	ResourceQueue     = "api-go.g5.resource"
	DLQ               = "api-go.g5.resource.dlq"
	NotificationQueue = "api-go.g7.notification"
	NotificationDLQ   = "api-go.g7.notification.dlq"
)

var retryQueues = []struct {
	Name  string
	Delay time.Duration
}{{"api-go.g5.resource.retry.1m", time.Minute}, {"api-go.g5.resource.retry.5m", 5 * time.Minute}, {"api-go.g5.resource.retry.30m", 30 * time.Minute}}

var notificationRetryQueues = []struct {
	Name  string
	Delay time.Duration
}{{"api-go.g7.notification.retry.1m", time.Minute}, {"api-go.g7.notification.retry.5m", 5 * time.Minute}, {"api-go.g7.notification.retry.30m", 30 * time.Minute}}

type Client struct {
	connection *amqp091.Connection
	channel    *amqp091.Channel
}

func Open(url string) (*Client, error) {
	if strings.TrimSpace(url) == "" {
		return nil, fmt.Errorf("RABBITMQ_URL must not be empty")
	}
	connection, err := amqp091.Dial(url)
	if err != nil {
		return nil, fmt.Errorf("connect RabbitMQ: %w", err)
	}
	channel, err := connection.Channel()
	if err != nil {
		_ = connection.Close()
		return nil, fmt.Errorf("open RabbitMQ channel: %w", err)
	}
	client := &Client{connection: connection, channel: channel}
	if err := client.Declare(); err != nil {
		_ = client.Close()
		return nil, err
	}
	return client, nil
}

func (c *Client) Declare() error {
	if err := c.channel.ExchangeDeclare(PartnerExchange, "topic", true, false, false, false, nil); err != nil {
		return fmt.Errorf("declare partner exchange: %w", err)
	}
	if err := c.channel.ExchangeDeclare(InternalExchange, "topic", true, false, false, false, nil); err != nil {
		return fmt.Errorf("declare internal exchange: %w", err)
	}
	if _, err := c.channel.QueueDeclare(ResourceQueue, true, false, false, false, nil); err != nil {
		return fmt.Errorf("declare resource queue: %w", err)
	}
	if err := c.channel.QueueBind(ResourceQueue, "resource.#", PartnerExchange, false, nil); err != nil {
		return fmt.Errorf("bind resource queue: %w", err)
	}
	if _, err := c.channel.QueueDeclare(DLQ, true, false, false, false, nil); err != nil {
		return fmt.Errorf("declare DLQ: %w", err)
	}
	if _, err := c.channel.QueueDeclare(NotificationQueue, true, false, false, false, nil); err != nil {
		return fmt.Errorf("declare notification queue: %w", err)
	}
	if err := c.channel.QueueBind(NotificationQueue, "notification.delivery.requested", InternalExchange, false, nil); err != nil {
		return fmt.Errorf("bind notification queue: %w", err)
	}
	if _, err := c.channel.QueueDeclare(NotificationDLQ, true, false, false, false, nil); err != nil {
		return fmt.Errorf("declare notification DLQ: %w", err)
	}
	for _, retry := range notificationRetryQueues {
		args := amqp091.Table{"x-message-ttl": int32(retry.Delay.Milliseconds()), "x-dead-letter-exchange": InternalExchange, "x-dead-letter-routing-key": "notification.delivery.requested"}
		if _, err := c.channel.QueueDeclare(retry.Name, true, false, false, false, args); err != nil {
			return fmt.Errorf("declare notification retry queue %s: %w", retry.Name, err)
		}
	}
	for _, retry := range retryQueues {
		args := amqp091.Table{"x-message-ttl": int32(retry.Delay.Milliseconds()), "x-dead-letter-exchange": PartnerExchange, "x-dead-letter-routing-key": "resource.retry"}
		if _, err := c.channel.QueueDeclare(retry.Name, true, false, false, false, args); err != nil {
			return fmt.Errorf("declare retry queue %s: %w", retry.Name, err)
		}
	}
	return nil
}

func (c *Client) Deliveries() (<-chan amqp091.Delivery, error) {
	return c.channel.Consume(ResourceQueue, "", false, false, false, false, nil)
}

func (c *Client) NotificationDeliveries() (<-chan amqp091.Delivery, error) {
	return c.channel.Consume(NotificationQueue, "", false, false, false, false, nil)
}

// RetryNotification preserves manual acknowledgement. The final retry is
// durably wrapped in the G7 DLQ before the source delivery is acknowledged.
func (c *Client) RetryNotification(delivery amqp091.Delivery, retry int, reason string) (bool, error) {
	if retry >= len(notificationRetryQueues) {
		payload, err := json.Marshal(struct {
			Envelope      json.RawMessage `json:"envelope"`
			FailureReason string          `json:"failure_reason"`
		}{Envelope: delivery.Body, FailureReason: reason})
		if err != nil {
			return false, err
		}
		if err := c.channel.PublishWithContext(context.Background(), "", NotificationDLQ, false, false, amqp091.Publishing{ContentType: "application/json", Body: payload, CorrelationId: delivery.CorrelationId, DeliveryMode: amqp091.Persistent}); err != nil {
			return false, err
		}
		return true, delivery.Ack(false)
	}
	headers := cloneHeaders(delivery.Headers)
	headers["x-g7-retry-count"] = retry + 1
	headers["x-g7-failure-reason"] = reason
	if err := c.channel.PublishWithContext(context.Background(), "", notificationRetryQueues[retry].Name, false, false, amqp091.Publishing{ContentType: delivery.ContentType, Body: delivery.Body, CorrelationId: delivery.CorrelationId, MessageId: delivery.MessageId, Headers: headers, DeliveryMode: amqp091.Persistent}); err != nil {
		return false, fmt.Errorf("publish notification retry: %w", err)
	}
	return false, delivery.Ack(false)
}

func (c *Client) Retry(delivery amqp091.Delivery, retry int, reason string) error {
	if retry >= len(retryQueues) {
		if err := c.deadLetter(delivery, reason); err != nil {
			return err
		}
		return delivery.Ack(false)
	}
	headers := cloneHeaders(delivery.Headers)
	headers["x-g5-retry-count"] = retry + 1
	headers["x-g5-failure-reason"] = reason
	if err := c.channel.PublishWithContext(context.Background(), "", retryQueues[retry].Name, false, false, amqp091.Publishing{ContentType: delivery.ContentType, Body: delivery.Body, CorrelationId: delivery.CorrelationId, MessageId: delivery.MessageId, Headers: headers, DeliveryMode: amqp091.Persistent}); err != nil {
		return fmt.Errorf("publish retry: %w", err)
	}
	return delivery.Ack(false)
}

func (c *Client) Quarantine(delivery amqp091.Delivery, reason string) error {
	if err := c.deadLetter(delivery, reason); err != nil {
		return err
	}
	return delivery.Ack(false)
}
func (c *Client) deadLetter(delivery amqp091.Delivery, reason string) error {
	payload, err := json.Marshal(struct {
		Envelope      json.RawMessage `json:"envelope"`
		FailureReason string          `json:"failure_reason"`
	}{Envelope: delivery.Body, FailureReason: reason})
	if err != nil {
		return err
	}
	return c.channel.PublishWithContext(context.Background(), "", DLQ, false, false, amqp091.Publishing{ContentType: "application/json", Body: payload, CorrelationId: delivery.CorrelationId, MessageId: delivery.MessageId, DeliveryMode: amqp091.Persistent})
}

func (c *Client) PublishConfirmed(ctx context.Context, routingKey string, payload []byte, correlationID string) error {
	if err := c.channel.Confirm(false); err != nil {
		return fmt.Errorf("enable publisher confirms: %w", err)
	}
	confirms := c.channel.NotifyPublish(make(chan amqp091.Confirmation, 1))
	if err := c.channel.PublishWithContext(ctx, InternalExchange, routingKey, false, false, amqp091.Publishing{ContentType: "application/json", Body: payload, CorrelationId: correlationID, DeliveryMode: amqp091.Persistent}); err != nil {
		return fmt.Errorf("publish internal event: %w", err)
	}
	select {
	case confirmation := <-confirms:
		if !confirmation.Ack {
			return fmt.Errorf("broker negatively acknowledged publish")
		}
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Ping opens a short-lived channel so health reflects a usable broker
// connection rather than only the local connection object's closed flag.
func (c *Client) Ping(_ context.Context) error {
	if c == nil || c.connection == nil || c.connection.IsClosed() {
		return fmt.Errorf("RabbitMQ connection is unavailable")
	}
	channel, err := c.connection.Channel()
	if err != nil {
		return fmt.Errorf("open RabbitMQ probe channel: %w", err)
	}
	return channel.Close()
}
func (c *Client) Close() error {
	if c.channel != nil {
		_ = c.channel.Close()
	}
	if c.connection != nil {
		return c.connection.Close()
	}
	return nil
}
func cloneHeaders(headers amqp091.Table) amqp091.Table {
	copy := amqp091.Table{}
	for k, v := range headers {
		copy[k] = v
	}
	return copy
}
