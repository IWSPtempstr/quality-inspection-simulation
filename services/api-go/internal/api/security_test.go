package api

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/gin-gonic/gin"
)

func TestSessionRequiresVerifiedCookie(t *testing.T) {
	router := NewRouter(testLogger(), AuthenticatorFunc(func(context.Context, string) (entities.Actor, error) {
		return entities.Actor{ID: "scheduler-001", CenterID: "center-a", DisplayName: "王调度", Roles: []entities.Role{entities.RoleScheduler}}, nil
	}))

	request := httptest.NewRequest(http.MethodGet, "/api/v1/session/me", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("status without cookie = %d, want %d", response.Code, http.StatusUnauthorized)
	}
	if contentType := response.Header().Get("Content-Type"); contentType != "application/problem+json; charset=utf-8" {
		t.Fatalf("content type = %q, want RFC 9457 problem response", contentType)
	}
}

func TestSessionReturnsActorFromVerifiedClaims(t *testing.T) {
	router := NewRouter(testLogger(), AuthenticatorFunc(func(_ context.Context, cookie string) (entities.Actor, error) {
		if cookie != "verified-session" {
			return entities.Actor{}, errors.New("invalid session")
		}
		return entities.Actor{ID: "scheduler-001", CenterID: "center-a", DisplayName: "王调度", Roles: []entities.Role{entities.RoleScheduler}}, nil
	}))

	request := httptest.NewRequest(http.MethodGet, "/api/v1/session/me", nil)
	request.AddCookie(&http.Cookie{Name: SessionCookieName, Value: "verified-session"})
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}
	if response.Body.String() != `{"user_id":"scheduler-001","role":"scheduler","display_name":"王调度"}` {
		t.Fatalf("session response = %s", response.Body.String())
	}
}

func TestRequireCapabilityRejectsUnauthorizedRole(t *testing.T) {
	router := gin.New()
	router.Use(ActorMiddleware(AuthenticatorFunc(func(context.Context, string) (entities.Actor, error) {
		return entities.Actor{ID: "viewer-001", CenterID: "center-a", Roles: []entities.Role{entities.RoleViewer}}, nil
	})))
	router.GET("/protected", RequireCapability(entities.CapabilityScheduleWrite), func(c *gin.Context) {
		c.Status(http.StatusNoContent)
	})

	request := httptest.NewRequest(http.MethodGet, "/protected", nil)
	request.AddCookie(&http.Cookie{Name: SessionCookieName, Value: "verified-session"})
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusForbidden)
	}
}

func TestMutationPreconditionsRejectMissingAndMalformedHeaders(t *testing.T) {
	router := gin.New()
	router.POST("/create", RequireIdempotencyKey(), func(c *gin.Context) { c.Status(http.StatusCreated) })
	router.PATCH("/existing", RequireIdempotencyKey(), RequireVersion(), func(c *gin.Context) { c.Status(http.StatusNoContent) })

	for _, testCase := range []struct {
		name    string
		method  string
		path    string
		headers map[string]string
	}{
		{name: "missing idempotency key", method: http.MethodPost, path: "/create"},
		{name: "missing version", method: http.MethodPatch, path: "/existing", headers: map[string]string{"Idempotency-Key": "operation-1"}},
		{name: "malformed version", method: http.MethodPatch, path: "/existing", headers: map[string]string{"Idempotency-Key": "operation-1", "If-Match": "stale"}},
		{name: "valid headers", method: http.MethodPatch, path: "/existing", headers: map[string]string{"Idempotency-Key": "operation-1", "If-Match": "7"}},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			request := httptest.NewRequest(testCase.method, testCase.path, nil)
			for name, value := range testCase.headers {
				request.Header.Set(name, value)
			}
			response := httptest.NewRecorder()
			router.ServeHTTP(response, request)

			want := http.StatusBadRequest
			if testCase.name == "valid headers" {
				want = http.StatusNoContent
			}
			if response.Code != want {
				t.Fatalf("status = %d, want %d", response.Code, want)
			}
		})
	}
}

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}
