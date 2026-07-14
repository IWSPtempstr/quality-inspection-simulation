package oidc

import (
	"context"
	"fmt"

	gooidc "github.com/coreos/go-oidc/v3/oidc"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
)

type Verifier struct {
	verifier *gooidc.IDTokenVerifier
}

func NewVerifier(ctx context.Context, issuerURL, clientID string) (*Verifier, error) {
	provider, err := gooidc.NewProvider(ctx, issuerURL)
	if err != nil {
		return nil, fmt.Errorf("discover OIDC provider: %w", err)
	}
	return &Verifier{verifier: provider.Verifier(&gooidc.Config{ClientID: clientID})}, nil
}

func (verifier *Verifier) Authenticate(ctx context.Context, sessionToken string) (entities.Actor, error) {
	token, err := verifier.verifier.Verify(ctx, sessionToken)
	if err != nil {
		return entities.Actor{}, fmt.Errorf("verify OIDC session: %w", err)
	}
	var claims struct {
		Subject  string   `json:"sub"`
		Name     string   `json:"name"`
		CenterID string   `json:"center_id"`
		Roles    []string `json:"roles"`
	}
	if err := token.Claims(&claims); err != nil {
		return entities.Actor{}, fmt.Errorf("decode OIDC claims: %w", err)
	}
	if claims.Subject == "" || claims.CenterID == "" || len(claims.Roles) == 0 {
		return entities.Actor{}, fmt.Errorf("OIDC session is missing required actor claims")
	}
	actor := entities.Actor{ID: claims.Subject, CenterID: claims.CenterID, DisplayName: claims.Name}
	for _, value := range claims.Roles {
		switch role := entities.Role(value); role {
		case entities.RoleAdmin, entities.RoleScheduler, entities.RoleOperator, entities.RoleViewer:
			actor.Roles = append(actor.Roles, role)
		default:
			return entities.Actor{}, fmt.Errorf("OIDC session has unsupported role %q", value)
		}
	}
	return actor, nil
}
