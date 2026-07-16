package redis

import (
	"context"
	"fmt"
	"strings"
	"time"

	redislib "github.com/redis/go-redis/v9"
)

type Debouncer struct{ client *redislib.Client }

func Open(url string) (*Debouncer, error) {
	if strings.TrimSpace(url) == "" {
		return nil, fmt.Errorf("REDIS_URL must not be empty")
	}
	options, err := redislib.ParseURL(url)
	if err != nil {
		return nil, fmt.Errorf("parse REDIS_URL: %w", err)
	}
	return &Debouncer{client: redislib.NewClient(options)}, nil
}

func (d *Debouncer) SetFirst(ctx context.Context, centerID string, ttl time.Duration) (bool, error) {
	created, err := d.client.SetNX(ctx, "g5:resource-debounce:"+centerID, "1", ttl).Result()
	if err != nil {
		return false, fmt.Errorf("set Redis debounce key: %w", err)
	}
	return created, nil
}
func (d *Debouncer) AcquireApprovalLock(ctx context.Context, previewID string, ttl time.Duration) (bool, error) {
	created, err := d.client.SetNX(ctx, "g6:approval-lock:"+previewID, "1", ttl).Result()
	if err != nil {
		return false, fmt.Errorf("set Redis approval lock: %w", err)
	}
	return created, nil
}
func (d *Debouncer) ReleaseApprovalLock(ctx context.Context, previewID string) error {
	return d.client.Del(ctx, "g6:approval-lock:"+previewID).Err()
}
func (d *Debouncer) Ping(ctx context.Context) error {
	if d == nil || d.client == nil {
		return fmt.Errorf("redis client is unavailable")
	}
	return d.client.Ping(ctx).Err()
}
func (d *Debouncer) Close() error { return d.client.Close() }
