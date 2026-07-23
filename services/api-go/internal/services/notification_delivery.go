package services

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"gorm.io/gorm"
)

// NotificationChannel is deliberately narrow: webhook_stub is a controlled
// infrastructure boundary, while in_app delivery completes without a network call.
type NotificationChannel interface {
	Deliver(context.Context, string, json.RawMessage) error
}

// HTTPNotificationChannel delivers the immutable Outbox payload to the
// configured controlled webhook boundary. It intentionally exposes no
// credential details through returned errors.
type HTTPNotificationChannel struct {
	BaseURL    string
	Credential string
	Client     *http.Client
}

func (c HTTPNotificationChannel) Deliver(ctx context.Context, _ string, payload json.RawMessage) error {
	if strings.TrimSpace(c.BaseURL) == "" {
		return fmt.Errorf("notification webhook is not configured")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(c.BaseURL, "/"), bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("create notification webhook request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if credential := strings.TrimSpace(c.Credential); credential != "" {
		req.Header.Set("Authorization", "Bearer "+credential)
	}
	client := c.Client
	if client == nil {
		client = http.DefaultClient
	}
	response, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("send notification webhook: %w", err)
	}
	defer func() { _ = response.Body.Close() }()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 512))
	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		return fmt.Errorf("notification webhook returned status %d", response.StatusCode)
	}
	return nil
}

type NotificationDeliveryWorker struct {
	db      *gorm.DB
	channel NotificationChannel
}

type NotificationDeliveryRequest struct {
	CenterID       string `json:"center_id"`
	NotificationID string `json:"notification_id"`
	Channel        string `json:"channel"`
}

func NewNotificationDeliveryWorker(db *gorm.DB, channel NotificationChannel) NotificationDeliveryWorker {
	return NotificationDeliveryWorker{db: db, channel: channel}
}
func (w NotificationDeliveryWorker) Process(ctx context.Context, payload json.RawMessage) error {
	ref, err := notificationDeliveryRequest(payload)
	if err != nil {
		return err
	}
	if ref.Channel == "webhook_stub" && w.channel != nil {
		if err := w.channel.Deliver(ctx, ref.NotificationID, payload); err != nil {
			return fmt.Errorf("deliver notification: %w", err)
		}
	}
	now := time.Now().UTC()
	return w.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.WithContext(ctx).Table("notification_deliveries").Where("notification_id=? AND channel=?", ref.NotificationID, ref.Channel).Updates(map[string]any{"status": "sent", "sent_at": now, "updated_at": now, "attempts": gorm.Expr("attempts + 1")}).Error; err != nil {
			return err
		}
		return tx.WithContext(ctx).Table("notifications").Where("id=?", ref.NotificationID).Updates(map[string]any{"status": "sent", "updated_at": now}).Error
	})
}

func (w NotificationDeliveryWorker) MarkFailed(ctx context.Context, payload json.RawMessage, reason string) error {
	ref, err := notificationDeliveryRequest(payload)
	if err != nil {
		return err
	}
	now := time.Now().UTC()
	return w.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		failure := reason
		if err := tx.WithContext(ctx).Table("notification_deliveries").Where("notification_id=? AND channel=?", ref.NotificationID, ref.Channel).Updates(map[string]any{"status": "failed", "failure_reason": failure, "attempts": gorm.Expr("attempts + 1"), "updated_at": now}).Error; err != nil {
			return err
		}
		return tx.WithContext(ctx).Table("notifications").Where("id=?", ref.NotificationID).Update("status", "failed").Error
	})
}

func notificationDeliveryRequest(payload json.RawMessage) (NotificationDeliveryRequest, error) {
	var ref NotificationDeliveryRequest
	if err := json.Unmarshal(payload, &ref); err != nil {
		return NotificationDeliveryRequest{}, fmt.Errorf("decode notification delivery request: %w", err)
	}
	if ref.NotificationID == "" || (ref.Channel != "in_app" && ref.Channel != "webhook_stub") {
		return NotificationDeliveryRequest{}, fmt.Errorf("invalid notification delivery request")
	}
	return ref, nil
}
