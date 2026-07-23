package redis

import (
	"context"
	"encoding/json"
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

// PutSession stores an opaque browser-session payload. The browser only ever
// receives the generated key, never this JSON or an upstream OIDC token.
func (d *Debouncer) PutSession(ctx context.Context, key string, value []byte, ttl time.Duration) error {
	return d.client.Set(ctx, "i7:session:"+key, value, ttl).Err()
}

func (d *Debouncer) GetSession(ctx context.Context, key string) ([]byte, error) {
	value, err := d.client.Get(ctx, "i7:session:"+key).Bytes()
	if err == redislib.Nil {
		return nil, nil
	}
	return value, err
}

func (d *Debouncer) DeleteSession(ctx context.Context, key string) error {
	return d.client.Del(ctx, "i7:session:"+key).Err()
}

func (d *Debouncer) PutOIDCState(ctx context.Context, state string, value any, ttl time.Duration) error {
	payload, err := json.Marshal(value)
	if err != nil {
		return fmt.Errorf("marshal OIDC state: %w", err)
	}
	return d.client.Set(ctx, "i7:oidc-state:"+state, payload, ttl).Err()
}

// ConsumeOIDCState is deliberately single-use: deleting first prevents a
// replayed callback from exchanging the same authorization response twice.
func (d *Debouncer) ConsumeOIDCState(ctx context.Context, state string) ([]byte, error) {
	value, err := d.client.GetDel(ctx, "i7:oidc-state:"+state).Bytes()
	if err == redislib.Nil {
		return nil, nil
	}
	return value, err
}
