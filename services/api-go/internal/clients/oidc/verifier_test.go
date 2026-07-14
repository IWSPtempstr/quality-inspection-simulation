package oidc

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
)

func TestVerifierAcceptsVerifiedActorClaims(t *testing.T) {
	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("generate signing key: %v", err)
	}
	publicKey := jose.JSONWebKey{Key: &privateKey.PublicKey, KeyID: "test-key", Algorithm: string(jose.RS256), Use: "sig"}

	var issuer string
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/.well-known/openid-configuration":
			_ = json.NewEncoder(writer).Encode(map[string]string{"issuer": issuer, "jwks_uri": issuer + "/keys"})
		case "/keys":
			_ = json.NewEncoder(writer).Encode(jose.JSONWebKeySet{Keys: []jose.JSONWebKey{publicKey}})
		default:
			http.NotFound(writer, request)
		}
	}))
	defer server.Close()
	issuer = server.URL

	verifier, err := NewVerifier(context.Background(), issuer, "workbench")
	if err != nil {
		t.Fatalf("create verifier: %v", err)
	}
	token := signedToken(t, privateKey, issuer, "workbench", []string{"scheduler"})
	actor, err := verifier.Authenticate(context.Background(), token)
	if err != nil {
		t.Fatalf("authenticate verified token: %v", err)
	}
	if actor.ID != "scheduler-001" || actor.CenterID != "center-a" || len(actor.Roles) != 1 || actor.Roles[0] != entities.RoleScheduler {
		t.Fatalf("actor = %#v, want verified scheduler actor", actor)
	}
}

func signedToken(t *testing.T, privateKey *rsa.PrivateKey, issuer, audience string, roles []string) string {
	t.Helper()
	options := (&jose.SignerOptions{}).WithHeader("kid", "test-key")
	signer, err := jose.NewSigner(jose.SigningKey{Algorithm: jose.RS256, Key: privateKey}, options)
	if err != nil {
		t.Fatalf("create signer: %v", err)
	}
	token, err := jwt.Signed(signer).Claims(jwt.Claims{
		Issuer: issuer, Subject: "scheduler-001", Audience: jwt.Audience{audience}, Expiry: jwt.NewNumericDate(time.Now().Add(time.Hour)),
	}).Claims(map[string]any{"name": "王调度", "center_id": "center-a", "roles": roles}).Serialize()
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return token
}
