package services

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
)

type memorySessions struct {
	sessions map[string][]byte
	states   map[string][]byte
	err      error
}

func (m *memorySessions) PutSession(_ context.Context, key string, value []byte, _ time.Duration) error {
	if m.err != nil {
		return m.err
	}
	if m.sessions == nil {
		m.sessions = map[string][]byte{}
	}
	m.sessions[key] = value
	return nil
}
func (m *memorySessions) GetSession(_ context.Context, key string) ([]byte, error) {
	if m.err != nil {
		return nil, m.err
	}
	return m.sessions[key], nil
}
func (m *memorySessions) DeleteSession(_ context.Context, key string) error {
	if m.err != nil {
		return m.err
	}
	delete(m.sessions, key)
	return nil
}
func (m *memorySessions) PutOIDCState(_ context.Context, key string, value any, _ time.Duration) error {
	if m.err != nil {
		return m.err
	}
	payload, _ := json.Marshal(value)
	if m.states == nil {
		m.states = map[string][]byte{}
	}
	m.states[key] = payload
	return nil
}
func (m *memorySessions) ConsumeOIDCState(_ context.Context, key string) ([]byte, error) {
	if m.err != nil {
		return nil, m.err
	}
	value := m.states[key]
	delete(m.states, key)
	return value, nil
}

type fixtureOIDC struct{ err error }

func (f fixtureOIDC) AuthorizationURL(state, verifier, nonce string) string {
	return "https://issuer.example/authorize?state=" + state + "&code_challenge=" + verifier + "&nonce=" + nonce
}
func (f fixtureOIDC) Exchange(context.Context, string, string, string) (entities.Actor, error) {
	if f.err != nil {
		return entities.Actor{}, f.err
	}
	return entities.Actor{ID: "user-1", CenterID: "center-a", Roles: []entities.Role{entities.RoleScheduler}}, nil
}

func TestAuthenticationCompletesSingleUseCallbackAndCreatesOpaqueSession(t *testing.T) {
	repository := &memorySessions{}
	authentication := NewAuthentication(repository, fixtureOIDC{}, time.Hour)
	redirect, err := authentication.Begin(context.Background(), "/resources")
	if err != nil || redirect == "" || !strings.Contains(redirect, "nonce=") {
		t.Fatalf("Begin() = %q, %v", redirect, err)
	}
	var state string
	for key := range repository.states {
		state = key
	}
	sessionID, returnTo, err := authentication.Complete(context.Background(), state, "code")
	if err != nil || returnTo != "/resources" || sessionID == "" {
		t.Fatalf("Complete() = %q, %q, %v", sessionID, returnTo, err)
	}
	if string(repository.sessions[sessionID]) == "" || string(repository.sessions[sessionID]) == "code" {
		t.Fatal("session must be persisted without upstream code/token")
	}
	if _, _, err := authentication.Complete(context.Background(), state, "code"); !errors.Is(err, entities.ErrUnauthenticated) {
		t.Fatalf("replayed callback error = %v", err)
	}
}

func TestAuthenticationReturnsUnavailableWhenSessionStorageFails(t *testing.T) {
	authentication := NewAuthentication(&memorySessions{err: errors.New("redis down")}, fixtureOIDC{}, time.Hour)
	if _, err := authentication.Authenticate(context.Background(), "session"); !errors.Is(err, ErrSessionUnavailable) {
		t.Fatalf("Authenticate() error = %v", err)
	}
}
