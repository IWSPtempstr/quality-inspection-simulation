package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestInjectedHealthProbesAggregateWithoutLeakingFailures(t *testing.T) {
	secret := errors.New("amqp://secret:password@broker.example/partner-body")
	router := NewRouterWithOperations(testLogger(), nil, nil, "", HealthProbes{
		Postgres:     HealthProbeFunc(func(context.Context) error { return nil }),
		RabbitMQ:     HealthProbeFunc(func(context.Context) error { return secret }),
		Redis:        HealthProbeFunc(func(context.Context) error { return nil }),
		Partner:      HealthProbeFunc(func(context.Context) error { return nil }),
		Notification: HealthProbeFunc(func(context.Context) error { return nil }),
	})
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/v1/system/health", nil))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}
	var body struct {
		Status   string            `json:"status"`
		Services map[string]string `json:"services"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode health response: %v", err)
	}
	if body.Status != "degraded" || body.Services["rabbitmq"] != "degraded" || body.Services["postgres"] != "available" {
		t.Fatalf("health = %#v, want RabbitMQ degradation", body)
	}
	if got := response.Body.String(); strings.Contains(got, "secret") || strings.Contains(got, "password") || strings.Contains(got, "partner-body") || strings.Contains(got, "broker.example") {
		t.Fatalf("health response leaked probe error: %s", got)
	}
}

func TestInjectedPostgresFailureMakesHealthUnavailable(t *testing.T) {
	router := NewRouterWithOperations(testLogger(), nil, nil, "", HealthProbes{
		Postgres: HealthProbeFunc(func(context.Context) error { return errors.New("connection refused") }),
		Redis:    HealthProbeFunc(func(context.Context) error { return errors.New("connection refused") }),
	})
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/v1/system/health", nil))
	var body struct {
		Status   string            `json:"status"`
		Services map[string]string `json:"services"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode health response: %v", err)
	}
	if body.Status != "unavailable" || body.Services["postgres"] != "unavailable" || body.Services["redis"] != "degraded" {
		t.Fatalf("health = %#v, want unavailable PostgreSQL", body)
	}
}

func TestHTTPReachabilityProbeTreatsHTTPResponseAsAvailable(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = io.WriteString(w, "partner failure body")
	}))
	t.Cleanup(server.Close)
	if err := (HTTPReachabilityProbe{URL: server.URL}).Probe(context.Background()); err != nil {
		t.Fatalf("Probe() error = %v, want HTTP response treated as reachable", err)
	}
}
