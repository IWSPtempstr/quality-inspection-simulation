package rabbitmq

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"github.com/rabbitmq/amqp091-go"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestClientDeclaresDurableTopologyAndRoutesRetriesAndDLQ(t *testing.T) {
	ctx := context.Background()
	container := startRabbitMQ(t, ctx)
	t.Cleanup(func() { _ = container.Terminate(ctx) })

	url := rabbitURL(t, ctx, container)
	client, err := Open(url)
	if err != nil {
		t.Fatalf("open RabbitMQ client: %v", err)
	}
	t.Cleanup(func() { _ = client.Close() })

	for _, queue := range []string{ResourceQueue, DLQ} {
		// Redeclaring with the expected properties makes RabbitMQ reject a
		// topology regression rather than relying on client-side metadata.
		if _, err := client.channel.QueueDeclare(queue, true, false, false, false, nil); err != nil {
			t.Fatalf("verify durable queue %s: %v", queue, err)
		}
	}
	for _, retry := range retryQueues {
		args := amqp091.Table{"x-message-ttl": int32(retry.Delay.Milliseconds()), "x-dead-letter-exchange": PartnerExchange, "x-dead-letter-routing-key": "resource.retry"}
		if _, err := client.channel.QueueDeclare(retry.Name, true, false, false, false, args); err != nil {
			t.Fatalf("verify durable retry queue %s: %v", retry.Name, err)
		}
	}

	deliveries, err := client.Deliveries()
	if err != nil {
		t.Fatalf("consume resource queue: %v", err)
	}
	if err := client.channel.PublishWithContext(ctx, PartnerExchange, "resource.equipment", false, false, amqp091.Publishing{Body: []byte(`{"event_id":"source"}`), DeliveryMode: amqp091.Persistent}); err != nil {
		t.Fatalf("publish source delivery: %v", err)
	}
	delivery := nextDelivery(t, deliveries)
	if err := client.Retry(delivery, 0, "transient failure"); err != nil {
		t.Fatalf("route first retry: %v", err)
	}
	waitForQueueMessages(t, client.channel, retryQueues[0].Name, 1)

	if err := client.channel.PublishWithContext(ctx, PartnerExchange, "resource.equipment", false, false, amqp091.Publishing{Body: []byte(`{"event_id":"invalid"}`), CorrelationId: "correlation-1", DeliveryMode: amqp091.Persistent}); err != nil {
		t.Fatalf("publish DLQ source delivery: %v", err)
	}
	if err := client.Quarantine(nextDelivery(t, deliveries), "invalid payload"); err != nil {
		t.Fatalf("quarantine delivery: %v", err)
	}
	dlq, err := client.channel.Consume(DLQ, "", false, false, false, false, nil)
	if err != nil {
		t.Fatalf("consume DLQ: %v", err)
	}
	dlqDelivery := nextDelivery(t, dlq)
	var got struct {
		Envelope      json.RawMessage `json:"envelope"`
		FailureReason string          `json:"failure_reason"`
	}
	if err := json.Unmarshal(dlqDelivery.Body, &got); err != nil {
		t.Fatalf("decode DLQ wrapper: %v", err)
	}
	if string(got.Envelope) != `{"event_id":"invalid"}` || got.FailureReason != "invalid payload" {
		t.Fatalf("DLQ wrapper = %#v, want original envelope and failure reason", got)
	}
	if err := dlqDelivery.Ack(false); err != nil {
		t.Fatalf("ack DLQ delivery: %v", err)
	}
}

func TestClientPublishesInternalEventsWithBrokerConfirmation(t *testing.T) {
	ctx := context.Background()
	container := startRabbitMQ(t, ctx)
	t.Cleanup(func() { _ = container.Terminate(ctx) })
	client, err := Open(rabbitURL(t, ctx, container))
	if err != nil {
		t.Fatalf("open RabbitMQ client: %v", err)
	}
	t.Cleanup(func() { _ = client.Close() })

	const sink = "g5-confirm-sink"
	if _, err := client.channel.QueueDeclare(sink, true, true, false, false, nil); err != nil {
		t.Fatalf("declare confirm sink: %v", err)
	}
	if err := client.channel.QueueBind(sink, "schedule.rebuild.requested", InternalExchange, false, nil); err != nil {
		t.Fatalf("bind confirm sink: %v", err)
	}
	if err := client.PublishConfirmed(ctx, "schedule.rebuild.requested", []byte(`{"center_id":"center-a"}`), "correlation-2"); err != nil {
		t.Fatalf("publish confirmed event: %v", err)
	}
	messages, err := client.channel.Consume(sink, "", true, true, false, false, nil)
	if err != nil {
		t.Fatalf("consume confirmed event: %v", err)
	}
	message := nextDelivery(t, messages)
	if string(message.Body) != `{"center_id":"center-a"}` || message.CorrelationId != "correlation-2" {
		t.Fatalf("confirmed event = body %s correlation %q", message.Body, message.CorrelationId)
	}
}

func startRabbitMQ(t *testing.T, ctx context.Context) testcontainers.Container {
	t.Helper()
	container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{
		ContainerRequest: testcontainers.ContainerRequest{
			Image:        "rabbitmq:4-alpine",
			ExposedPorts: []string{"5672/tcp"},
			WaitingFor: wait.ForAll(
				wait.ForListeningPort("5672/tcp"),
				wait.ForLog("Server startup complete"),
			).WithDeadline(90 * time.Second),
		},
		Started: true,
	})
	if err != nil {
		t.Fatalf("start RabbitMQ container: %v", err)
	}
	return container
}

func rabbitURL(t *testing.T, ctx context.Context, container testcontainers.Container) string {
	t.Helper()
	host, err := container.Host(ctx)
	if err != nil {
		t.Fatalf("get RabbitMQ host: %v", err)
	}
	port, err := container.MappedPort(ctx, "5672/tcp")
	if err != nil {
		t.Fatalf("get RabbitMQ port: %v", err)
	}
	return fmt.Sprintf("amqp://guest:guest@%s:%s/", host, port.Port())
}

func nextDelivery(t *testing.T, deliveries <-chan amqp091.Delivery) amqp091.Delivery {
	t.Helper()
	select {
	case delivery := <-deliveries:
		return delivery
	case <-time.After(15 * time.Second):
		t.Fatal("timed out waiting for RabbitMQ delivery")
		return amqp091.Delivery{}
	}
}

func waitForQueueMessages(t *testing.T, channel *amqp091.Channel, queue string, want int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		state, err := channel.QueueDeclarePassive(queue, true, false, false, false, nil)
		if err != nil {
			t.Fatalf("inspect queue %s: %v", queue, err)
		}
		if state.Messages == want {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("queue %s messages = %d, want %d", queue, state.Messages, want)
		}
		time.Sleep(25 * time.Millisecond)
	}
}
