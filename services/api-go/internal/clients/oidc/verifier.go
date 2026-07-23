package oidc

import (
	"context"
	"fmt"
	"strings"

	gooidc "github.com/coreos/go-oidc/v3/oidc"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"golang.org/x/oauth2"
)

// Verifier supports both legacy verified-token authentication and the I7
// authorization-code BFF flow. The latter is the production entry point.
type Verifier struct {
	verifier    *gooidc.IDTokenVerifier
	provider    *gooidc.Provider
	oauthConfig oauth2.Config
	centerClaim string
	rolesClaim  string
}

func NewVerifier(ctx context.Context, issuerURL, clientID string) (*Verifier, error) {
	return NewClient(ctx, issuerURL, clientID, "", "", "center_id", "roles", []string{"openid", "profile"})
}

func NewClient(ctx context.Context, issuerURL, clientID, clientSecret, redirectURL, centerClaim, rolesClaim string, scopes []string) (*Verifier, error) {
	provider, err := gooidc.NewProvider(ctx, issuerURL)
	if err != nil {
		return nil, fmt.Errorf("discover OIDC provider: %w", err)
	}
	if strings.TrimSpace(centerClaim) == "" {
		centerClaim = "center_id"
	}
	if strings.TrimSpace(rolesClaim) == "" {
		rolesClaim = "roles"
	}
	if len(scopes) == 0 {
		scopes = []string{"openid", "profile"}
	}
	return &Verifier{
		provider:    provider,
		verifier:    provider.Verifier(&gooidc.Config{ClientID: clientID}),
		oauthConfig: oauth2.Config{ClientID: clientID, ClientSecret: clientSecret, RedirectURL: redirectURL, Endpoint: provider.Endpoint(), Scopes: scopes},
		centerClaim: centerClaim, rolesClaim: rolesClaim,
	}, nil
}

func (verifier *Verifier) Authenticate(ctx context.Context, sessionToken string) (entities.Actor, error) {
	token, err := verifier.verifier.Verify(ctx, sessionToken)
	if err != nil {
		return entities.Actor{}, fmt.Errorf("verify OIDC session: %w", err)
	}
	return verifier.actorFromToken(token)
}

func (verifier *Verifier) AuthorizationURL(state, codeVerifier, nonce string) string {
	return verifier.oauthConfig.AuthCodeURL(state, oauth2.S256ChallengeOption(codeVerifier), oauth2.SetAuthURLParam("nonce", nonce))
}

func (verifier *Verifier) Exchange(ctx context.Context, code, codeVerifier, nonce string) (entities.Actor, error) {
	token, err := verifier.oauthConfig.Exchange(ctx, code, oauth2.VerifierOption(codeVerifier))
	if err != nil {
		return entities.Actor{}, fmt.Errorf("exchange authorization code: %w", err)
	}
	rawIDToken, ok := token.Extra("id_token").(string)
	if !ok || strings.TrimSpace(rawIDToken) == "" {
		return entities.Actor{}, fmt.Errorf("OIDC token response is missing id_token")
	}
	idToken, err := verifier.verifier.Verify(ctx, rawIDToken)
	if err != nil {
		return entities.Actor{}, fmt.Errorf("verify OIDC ID token: %w", err)
	}
	if idToken.Nonce != nonce {
		return entities.Actor{}, fmt.Errorf("OIDC ID token nonce does not match login request")
	}
	return verifier.actorFromToken(idToken)
}

func (verifier *Verifier) actorFromToken(token *gooidc.IDToken) (entities.Actor, error) {
	var raw map[string]any
	if err := token.Claims(&raw); err != nil {
		return entities.Actor{}, fmt.Errorf("decode OIDC claims: %w", err)
	}
	subject, _ := raw["sub"].(string)
	name, _ := raw["name"].(string)
	centerID, _ := raw[verifier.centerClaim].(string)
	roles, ok := stringSlice(raw[verifier.rolesClaim])
	if subject == "" || centerID == "" || !ok || len(roles) == 0 {
		return entities.Actor{}, fmt.Errorf("OIDC session is missing required actor claims")
	}
	actor := entities.Actor{ID: subject, CenterID: centerID, DisplayName: name}
	for _, value := range roles {
		switch role := entities.Role(value); role {
		case entities.RoleAdmin, entities.RoleScheduler, entities.RoleOperator, entities.RoleViewer:
			actor.Roles = append(actor.Roles, role)
		default:
			return entities.Actor{}, fmt.Errorf("OIDC session has unsupported role %q", value)
		}
	}
	return actor, nil
}

func stringSlice(value any) ([]string, bool) {
	switch values := value.(type) {
	case []any:
		out := make([]string, 0, len(values))
		for _, value := range values {
			item, ok := value.(string)
			if !ok {
				return nil, false
			}
			out = append(out, item)
		}
		return out, true
	case []string:
		return values, true
	case string:
		return strings.Fields(values), true
	default:
		return nil, false
	}
}
