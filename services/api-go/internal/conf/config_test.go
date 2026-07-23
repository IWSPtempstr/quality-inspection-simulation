package conf

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLoadUsesDevelopmentDefaults(t *testing.T) {
	config, err := Load(func(string) (string, bool) { return "", false })
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if config.Environment != "development" || config.HTTPAddress != ":8080" {
		t.Fatalf("config = %#v, want development defaults", config)
	}
}

func TestLoadReadsSecretValuesFromFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "oidc-secret")
	if err := os.WriteFile(path, []byte("from-secret-file\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	config, err := Load(func(key string) (string, bool) {
		switch key {
		case "OIDC_CLIENT_SECRET_FILE":
			return path, true
		case "SESSION_TTL_SECONDS":
			return "120", true
		default:
			return "", false
		}
	})
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if config.OIDCClientSecret != "from-secret-file" || config.SessionTTL != 2*time.Minute {
		t.Fatalf("config = %#v", config)
	}
}

func TestProductionRejectsStubAndMissingExternalConfiguration(t *testing.T) {
	config := Config{Environment: "production", HTTPAddress: ":8080", DatabaseURL: "postgres://db", RabbitMQURL: "amqp://broker", RedisURL: "redis://cache", OIDCIssuerURL: "http://ops-stub:8080/realms/demo", OIDCClientID: "client", OIDCClientSecret: "secret", OIDCRedirectURL: "https://app.example/api/v1/auth/callback", PublicAppURL: "https://app.example", InternalServiceToken: "service", PartnerScheduleURL: "https://partner.example", PartnerScheduleCredential: "partner", NotificationWebhookURL: "https://notify.example", NotificationWebhookCredential: "notify", SessionTTL: time.Hour}
	if err := config.Validate(); err == nil {
		t.Fatal("Validate() error = nil, want non-production issuer rejection")
	}
}

func TestLoadRejectsBlankConfiguredAddress(t *testing.T) {
	_, err := Load(func(key string) (string, bool) {
		if key == "HTTP_ADDR" {
			return " ", true
		}
		return "", false
	})
	if err == nil {
		t.Fatal("Load() error = nil, want validation error")
	}
}
