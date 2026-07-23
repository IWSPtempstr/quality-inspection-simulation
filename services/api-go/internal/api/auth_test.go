package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
)

type authTestRepository struct{ sessions, states map[string][]byte }

func (r *authTestRepository) PutSession(_ context.Context, key string, value []byte, _ time.Duration) error {
	if r.sessions == nil {
		r.sessions = map[string][]byte{}
	}
	r.sessions[key] = value
	return nil
}
func (r *authTestRepository) GetSession(_ context.Context, key string) ([]byte, error) {
	return r.sessions[key], nil
}
func (r *authTestRepository) DeleteSession(_ context.Context, key string) error {
	delete(r.sessions, key)
	return nil
}
func (r *authTestRepository) PutOIDCState(_ context.Context, key string, value any, _ time.Duration) error {
	data, _ := json.Marshal(value)
	if r.states == nil {
		r.states = map[string][]byte{}
	}
	r.states[key] = data
	return nil
}
func (r *authTestRepository) ConsumeOIDCState(_ context.Context, key string) ([]byte, error) {
	data := r.states[key]
	delete(r.states, key)
	return data, nil
}

type authTestProvider struct{}

func (authTestProvider) AuthorizationURL(state, _, nonce string) string {
	return "https://issuer.example/authorize?state=" + state + "&nonce=" + nonce
}
func (authTestProvider) Exchange(context.Context, string, string, string) (entities.Actor, error) {
	return entities.Actor{ID: "user-1", CenterID: "center-a", Roles: []entities.Role{entities.RoleScheduler}}, nil
}

type rejectedAuthTestProvider struct{ authTestProvider }

func (rejectedAuthTestProvider) Exchange(context.Context, string, string, string) (entities.Actor, error) {
	return entities.Actor{}, context.DeadlineExceeded
}

func TestAuthenticationRoutesRejectOpenRedirectAndRequireCSRFForLogout(t *testing.T) {
	repository := &authTestRepository{}
	authentication := services.NewAuthentication(repository, authTestProvider{}, time.Hour)
	router := NewRouterWithG8AndAuthentication(testLogger(), nil, nil, "", HealthProbes{}, nil, authentication, true)

	invalid := httptest.NewRequest(http.MethodGet, "/api/v1/auth/login?return_to=https://evil.example", nil)
	invalidResponse := httptest.NewRecorder()
	router.ServeHTTP(invalidResponse, invalid)
	if invalidResponse.Code != http.StatusBadRequest {
		t.Fatalf("open redirect status = %d", invalidResponse.Code)
	}

	login := httptest.NewRequest(http.MethodGet, "/api/v1/auth/login?return_to=/resources", nil)
	loginResponse := httptest.NewRecorder()
	router.ServeHTTP(loginResponse, login)
	if loginResponse.Code != http.StatusFound {
		t.Fatalf("login status = %d", loginResponse.Code)
	}
	var state string
	for key := range repository.states {
		state = key
	}
	callback := httptest.NewRequest(http.MethodGet, "/api/v1/auth/callback?state="+state+"&code=fixture", nil)
	callbackResponse := httptest.NewRecorder()
	router.ServeHTTP(callbackResponse, callback)
	if callbackResponse.Code != http.StatusFound {
		t.Fatalf("callback status = %d", callbackResponse.Code)
	}
	cookies := callbackResponse.Result().Cookies()
	if len(cookies) != 1 || cookies[0].Name != SessionCookieName || !cookies[0].HttpOnly || !cookies[0].Secure || cookies[0].Value == "fixture" {
		t.Fatalf("unsafe session cookie: %#v", cookies)
	}

	logout := httptest.NewRequest(http.MethodPost, "/api/v1/auth/logout", nil)
	logout.AddCookie(cookies[0])
	logoutResponse := httptest.NewRecorder()
	router.ServeHTTP(logoutResponse, logout)
	if logoutResponse.Code != http.StatusForbidden {
		t.Fatalf("logout without CSRF status = %d", logoutResponse.Code)
	}
}

func TestAuthenticationCallbackFailureUsesLoginFailureRoute(t *testing.T) {
	repository := &authTestRepository{}
	authentication := services.NewAuthentication(repository, rejectedAuthTestProvider{}, time.Hour)
	router := NewRouterWithG8AndAuthentication(testLogger(), nil, nil, "", HealthProbes{}, nil, authentication, true)
	login := httptest.NewRequest(http.MethodGet, "/api/v1/auth/login", nil)
	loginResponse := httptest.NewRecorder()
	router.ServeHTTP(loginResponse, login)
	var state string
	for key := range repository.states {
		state = key
	}
	callback := httptest.NewRequest(http.MethodGet, "/api/v1/auth/callback?state="+state+"&code=private-provider-detail", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, callback)
	if response.Code != http.StatusFound || response.Header().Get("Location") != "/login?reason=callback_failed" {
		t.Fatalf("callback failure = %d %q", response.Code, response.Header().Get("Location"))
	}
}

func TestLocalReturnToRejectsControlCharacters(t *testing.T) {
	if got := localReturnTo("/resources\r\nLocation: https://evil.example"); got != "" {
		t.Fatalf("localReturnTo() = %q", got)
	}
}
