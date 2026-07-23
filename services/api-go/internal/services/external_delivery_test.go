package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHTTPPartnerClientSendsOptionalCredentialWithoutChangingPayload(t *testing.T) {
	const credential = "partner-secret"
	var body string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if got := request.Header.Get("Authorization"); got != "Bearer "+credential {
			t.Errorf("Authorization = %q", got)
		}
		if got := request.Header.Get("If-Match"); got != "7" {
			t.Errorf("If-Match = %q", got)
		}
		bytes, _ := io.ReadAll(request.Body)
		body = string(bytes)
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	payload := []byte(`{"center_id":"center-a","preview_id":"preview-a"}`)
	client := HTTPPartnerClient{BaseURL: server.URL, Credential: credential, Client: server.Client()}
	status, response, err := client.PutSchedule(context.Background(), "center-a", 8, payload, "event-a", 7)
	if err != nil || status != http.StatusNoContent || response != "" {
		t.Fatalf("PutSchedule = (%d, %q, %v)", status, response, err)
	}
	if body != string(payload) {
		t.Fatalf("payload = %s, want %s", body, payload)
	}
}

func TestHTTPPartnerClientOmitsBlankCredential(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if got := request.Header.Get("Authorization"); got != "" {
			t.Errorf("Authorization = %q, want empty", got)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	_, _, err := (HTTPPartnerClient{BaseURL: server.URL, Credential: "  ", Client: server.Client()}).PutSchedule(context.Background(), "center-a", 1, []byte(`{}`), "event-a", 0)
	if err != nil {
		t.Fatalf("PutSchedule: %v", err)
	}
}

func TestHTTPNotificationChannelSendsCredentialAndPayload(t *testing.T) {
	const credential = "webhook-secret"
	payload := json.RawMessage(`{"center_id":"center-a","notification_id":"notice-a","channel":"webhook_stub"}`)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodPost {
			t.Errorf("method = %s", request.Method)
		}
		if got := request.Header.Get("Authorization"); got != "Bearer "+credential {
			t.Errorf("Authorization = %q", got)
		}
		var received any
		if err := json.NewDecoder(request.Body).Decode(&received); err != nil {
			t.Fatalf("decode payload: %v", err)
		}
		var expected any
		_ = json.Unmarshal(payload, &expected)
		if fmt.Sprint(received) != fmt.Sprint(expected) {
			t.Errorf("payload = %v, want %v", received, expected)
		}
		w.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()

	channel := HTTPNotificationChannel{BaseURL: server.URL, Credential: credential, Client: server.Client()}
	if err := channel.Deliver(context.Background(), "notice-a", payload); err != nil {
		t.Fatalf("Deliver: %v", err)
	}
}

func TestHTTPNotificationChannelFailureDoesNotExposeCredential(t *testing.T) {
	const credential = "never-return-this"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer server.Close()

	err := (HTTPNotificationChannel{BaseURL: server.URL, Credential: credential, Client: server.Client()}).Deliver(context.Background(), "notice-a", json.RawMessage(`{}`))
	if err == nil {
		t.Fatal("Deliver error = nil")
	}
	if strings.Contains(err.Error(), credential) {
		t.Fatalf("error leaks credential: %v", err)
	}
}
