package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client is a fixed-path service-authenticated adapter. It never accepts a
// caller-provided URL or operation name.
type Client struct {
	baseURL, token string
	http           *http.Client
}

func New(baseURL, token string) *Client {
	return &Client{baseURL: strings.TrimRight(baseURL, "/"), token: token, http: &http.Client{Timeout: 5 * time.Second}}
}
func (c *Client) Diagnose(ctx context.Context, payload json.RawMessage) (json.RawMessage, error) {
	return c.post(ctx, "/internal/v1/diagnoses", payload)
}
func (c *Client) ExplainSchedule(ctx context.Context, payload json.RawMessage) (json.RawMessage, error) {
	return c.post(ctx, "/internal/v1/schedule-explanations", payload)
}
func (c *Client) ExplainDataQuality(ctx context.Context, payload json.RawMessage) (json.RawMessage, error) {
	return c.post(ctx, "/internal/v1/data-quality-explanations", payload)
}
func (c *Client) CreateCaseCandidate(ctx context.Context, payload json.RawMessage) (json.RawMessage, error) {
	return c.post(ctx, "/internal/v1/exception-case-candidates", payload)
}
func (c *Client) SuggestAuditFilters(ctx context.Context, payload json.RawMessage) (json.RawMessage, error) {
	return c.post(ctx, "/internal/v1/audit-filter-suggestions", payload)
}
func (c *Client) DraftNotificationBody(ctx context.Context, payload json.RawMessage) (json.RawMessage, error) {
	return c.post(ctx, "/internal/v1/notification-body-drafts", payload)
}

func (c *Client) post(ctx context.Context, path string, payload json.RawMessage) (json.RawMessage, error) {
	if c == nil || c.baseURL == "" || c.token == "" {
		return nil, fmt.Errorf("ai service is unavailable")
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Authorization", "Bearer "+c.token)
	request.Header.Set("Content-Type", "application/json")
	response, err := c.http.Do(request)
	if err != nil {
		return nil, fmt.Errorf("call ai service: %w", err)
	}
	defer func() { _ = response.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(response.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 || !json.Valid(body) {
		return nil, fmt.Errorf("ai service unavailable")
	}
	return json.RawMessage(body), nil
}
