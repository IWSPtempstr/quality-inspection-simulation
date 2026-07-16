package redis

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestDebouncerUsesRedisSetNXWithConfiguredTTL(t *testing.T) {
	ctx := context.Background()
	container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{
		ContainerRequest: testcontainers.ContainerRequest{Image: "redis:7-alpine", ExposedPorts: []string{"6379/tcp"}, WaitingFor: wait.ForListeningPort("6379/tcp").WithStartupTimeout(60 * time.Second)},
		Started:          true,
	})
	if err != nil {
		t.Fatalf("start Redis container: %v", err)
	}
	t.Cleanup(func() { _ = container.Terminate(ctx) })
	host, err := container.Host(ctx)
	if err != nil {
		t.Fatalf("get Redis host: %v", err)
	}
	port, err := container.MappedPort(ctx, "6379/tcp")
	if err != nil {
		t.Fatalf("get Redis port: %v", err)
	}

	debouncer, err := Open(fmt.Sprintf("redis://%s:%s/0", host, port.Port()))
	if err != nil {
		t.Fatalf("open Redis debouncer: %v", err)
	}
	t.Cleanup(func() { _ = debouncer.Close() })
	first, err := debouncer.SetFirst(ctx, "center-a", 45*time.Second)
	if err != nil || !first {
		t.Fatalf("first SET NX = (%v, %v), want (true, nil)", first, err)
	}
	second, err := debouncer.SetFirst(ctx, "center-a", 45*time.Second)
	if err != nil || second {
		t.Fatalf("second SET NX = (%v, %v), want (false, nil)", second, err)
	}
	ttl, err := debouncer.client.TTL(ctx, "g5:resource-debounce:center-a").Result()
	if err != nil || ttl <= 0 || ttl > 45*time.Second {
		t.Fatalf("debounce TTL = (%s, %v), want (0s, 45s]", ttl, err)
	}
}

func TestDebouncerReturnsErrorWhenRedisIsUnavailable(t *testing.T) {
	debouncer, err := Open("redis://127.0.0.1:1/0")
	if err != nil {
		t.Fatalf("construct unavailable Redis client: %v", err)
	}
	t.Cleanup(func() { _ = debouncer.Close() })
	ctx, cancel := context.WithTimeout(context.Background(), 250*time.Millisecond)
	defer cancel()
	if _, err := debouncer.SetFirst(ctx, "center-a", time.Second); err == nil {
		t.Fatal("SetFirst() error = nil for unavailable Redis")
	}
}
