package main

import (
	"context"
	"sync/atomic"
	"testing"
	"time"
)

type countingOutboxPublisher struct{ calls atomic.Int32 }

func (p *countingOutboxPublisher) PublishPending(context.Context, int) error {
	p.calls.Add(1)
	return nil
}

func TestPublishPendingPeriodicallyRetriesWithoutDeliveries(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	publisher := &countingOutboxPublisher{}
	done := make(chan struct{})
	go func() {
		publishPendingPeriodically(ctx, publisher, 5*time.Millisecond)
		close(done)
	}()

	deadline := time.After(250 * time.Millisecond)
	for publisher.calls.Load() < 2 {
		select {
		case <-deadline:
			t.Fatalf("PublishPending calls = %d, want at least 2 without a delivery", publisher.calls.Load())
		case <-time.After(time.Millisecond):
		}
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("periodic publisher did not stop after context cancellation")
	}
}
