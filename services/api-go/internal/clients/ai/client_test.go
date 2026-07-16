package ai

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return fn(request) }

func TestClientUsesFixedInternalPathAndBearerServiceAuth(t *testing.T) {
	client := New("https://ai.example.test/", "service-token")
	client.http = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.String() != "https://ai.example.test/internal/v1/notification-body-drafts" {
			t.Fatalf("URL = %q", request.URL.String())
		}
		if request.Header.Get("Authorization") != "Bearer service-token" {
			t.Fatalf("Authorization = %q", request.Header.Get("Authorization"))
		}
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(`{"body":"draft","degraded":false}`)), Header: make(http.Header)}, nil
	})}
	result, err := client.DraftNotificationBody(context.Background(), json.RawMessage(`{"notification_id":"n"}`))
	if err != nil || string(result) != `{"body":"draft","degraded":false}` {
		t.Fatalf("DraftNotificationBody() = (%s, %v)", result, err)
	}
}
