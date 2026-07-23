package services

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
)

var ErrSessionUnavailable = errors.New("session storage unavailable")

type SessionRepository interface {
	PutSession(context.Context, string, []byte, time.Duration) error
	GetSession(context.Context, string) ([]byte, error)
	DeleteSession(context.Context, string) error
	PutOIDCState(context.Context, string, any, time.Duration) error
	ConsumeOIDCState(context.Context, string) ([]byte, error)
}

type OIDCProvider interface {
	AuthorizationURL(state, codeVerifier, nonce string) string
	Exchange(context.Context, string, string, string) (entities.Actor, error)
}

type Session struct {
	Actor entities.Actor `json:"actor"`
	CSRF  string         `json:"csrf"`
}

type oidcState struct {
	ReturnTo     string `json:"return_to"`
	CodeVerifier string `json:"code_verifier"`
	Nonce        string `json:"nonce"`
}

// Authentication owns opaque BFF session lifecycle. OIDC tokens are consumed
// during callback validation and intentionally never persisted in this layer.
type Authentication struct {
	repository SessionRepository
	provider   OIDCProvider
	sessionTTL time.Duration
	stateTTL   time.Duration
}

func NewAuthentication(repository SessionRepository, provider OIDCProvider, sessionTTL time.Duration) *Authentication {
	if sessionTTL <= 0 {
		sessionTTL = 8 * time.Hour
	}
	return &Authentication{repository: repository, provider: provider, sessionTTL: sessionTTL, stateTTL: 10 * time.Minute}
}

func (a *Authentication) Begin(ctx context.Context, returnTo string) (string, error) {
	state, err := randomURLValue(32)
	if err != nil {
		return "", err
	}
	verifier, err := randomURLValue(48)
	if err != nil {
		return "", err
	}
	nonce, err := randomURLValue(32)
	if err != nil {
		return "", err
	}
	if err := a.repository.PutOIDCState(ctx, state, oidcState{ReturnTo: returnTo, CodeVerifier: verifier, Nonce: nonce}, a.stateTTL); err != nil {
		return "", fmt.Errorf("store login state: %w", err)
	}
	return a.provider.AuthorizationURL(state, verifier, nonce), nil
}

func (a *Authentication) Complete(ctx context.Context, state, code string) (string, string, error) {
	payload, err := a.repository.ConsumeOIDCState(ctx, state)
	if err != nil {
		return "", "", fmt.Errorf("consume login state: %w", err)
	}
	if len(payload) == 0 {
		return "", "", entities.ErrUnauthenticated
	}
	var pending oidcState
	if err := json.Unmarshal(payload, &pending); err != nil {
		return "", "", entities.ErrUnauthenticated
	}
	actor, err := a.provider.Exchange(ctx, code, pending.CodeVerifier, pending.Nonce)
	if err != nil {
		return "", "", fmt.Errorf("exchange OIDC code: %w", err)
	}
	sessionID, err := randomURLValue(32)
	if err != nil {
		return "", "", err
	}
	csrf, err := randomURLValue(32)
	if err != nil {
		return "", "", err
	}
	stored, err := json.Marshal(Session{Actor: actor, CSRF: csrf})
	if err != nil {
		return "", "", fmt.Errorf("marshal session: %w", err)
	}
	if err := a.repository.PutSession(ctx, sessionID, stored, a.sessionTTL); err != nil {
		return "", "", fmt.Errorf("store browser session: %w", err)
	}
	return sessionID, pending.ReturnTo, nil
}

func (a *Authentication) Authenticate(ctx context.Context, sessionID string) (entities.Actor, error) {
	session, err := a.session(ctx, sessionID)
	if err != nil {
		return entities.Actor{}, err
	}
	return session.Actor, nil
}

func (a *Authentication) CSRF(ctx context.Context, sessionID string) (string, error) {
	session, err := a.session(ctx, sessionID)
	if err != nil {
		return "", err
	}
	return session.CSRF, nil
}

func (a *Authentication) ValidateCSRF(ctx context.Context, sessionID, value string) error {
	csrf, err := a.CSRF(ctx, sessionID)
	if err != nil {
		return err
	}
	if value == "" || csrf != value {
		return entities.ErrForbidden
	}
	return nil
}

func (a *Authentication) Logout(ctx context.Context, sessionID string) error {
	if err := a.repository.DeleteSession(ctx, sessionID); err != nil {
		return fmt.Errorf("delete browser session: %w", err)
	}
	return nil
}

func (a *Authentication) session(ctx context.Context, sessionID string) (Session, error) {
	payload, err := a.repository.GetSession(ctx, sessionID)
	if err != nil {
		return Session{}, fmt.Errorf("%w: %v", ErrSessionUnavailable, err)
	}
	if len(payload) == 0 {
		return Session{}, entities.ErrUnauthenticated
	}
	var session Session
	if err := json.Unmarshal(payload, &session); err != nil || session.Actor.ID == "" || session.Actor.CenterID == "" || len(session.Actor.Roles) == 0 {
		return Session{}, entities.ErrUnauthenticated
	}
	return session, nil
}

func randomURLValue(bytes int) (string, error) {
	payload := make([]byte, bytes)
	if _, err := rand.Read(payload); err != nil {
		return "", fmt.Errorf("generate random value: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(payload), nil
}
