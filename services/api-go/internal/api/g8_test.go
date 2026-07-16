package api

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
)

type unavailableAssistance struct{}

func (unavailableAssistance) Diagnose(context.Context, json.RawMessage) (json.RawMessage, error) {
	return nil, context.DeadlineExceeded
}
func (unavailableAssistance) ExplainSchedule(context.Context, json.RawMessage) (json.RawMessage, error) {
	return nil, context.DeadlineExceeded
}
func (unavailableAssistance) ExplainDataQuality(context.Context, json.RawMessage) (json.RawMessage, error) {
	return nil, context.DeadlineExceeded
}
func (unavailableAssistance) CreateCaseCandidate(context.Context, json.RawMessage) (json.RawMessage, error) {
	return nil, context.DeadlineExceeded
}
func (unavailableAssistance) SuggestAuditFilters(context.Context, json.RawMessage) (json.RawMessage, error) {
	return nil, context.DeadlineExceeded
}
func (unavailableAssistance) DraftNotificationBody(context.Context, json.RawMessage) (json.RawMessage, error) {
	return nil, context.DeadlineExceeded
}

var _ services.AssistanceClient = unavailableAssistance{}

func TestG8DraftSendRequiresIfMatch(t *testing.T) {
	router := gin.New()
	api := router.Group("/api/v1")
	mountG8Routes(api, AuthenticatorFunc(func(context.Context, string) (entities.Actor, error) {
		return entities.Actor{ID: "scheduler", CenterID: "center-a", Roles: []entities.Role{entities.RoleScheduler}}, nil
	}), nil, unavailableAssistance{}, "test-secret")
	request := httptest.NewRequest(http.MethodPost, "/api/v1/notification-drafts/opaque/send", nil)
	request.AddCookie(&http.Cookie{Name: SessionCookieName, Value: "session"})
	request.Header.Set("Idempotency-Key", "draft-send-1")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("send without If-Match = %d, want %d", response.Code, http.StatusBadRequest)
	}
}

func TestDecodeAndRestorePreservesIdempotencyRequestBody(t *testing.T) {
	body := []byte(`{"source_hash":"sha256:source","body":"edited"}`)
	context, _ := gin.CreateTestContext(httptest.NewRecorder())
	context.Request = httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(body))
	var input struct {
		SourceHash string `json:"source_hash"`
		Body       string `json:"body"`
	}
	if err := decodeAndRestore(context, &input); err != nil {
		t.Fatalf("decodeAndRestore: %v", err)
	}
	restored, err := io.ReadAll(context.Request.Body)
	if err != nil || !bytes.Equal(restored, body) {
		t.Fatalf("restored body = %q, %v", restored, err)
	}
}
