package conf

import (
	"fmt"
	"strings"
)

type LookupEnv func(string) (string, bool)

type Config struct {
	Environment   string
	HTTPAddress   string
	DatabaseURL   string
	OIDCIssuerURL string
	OIDCClientID  string
}

func Load(lookup LookupEnv) (Config, error) {
	config := Config{
		Environment:   valueOrDefault(lookup, "APP_ENV", "development"),
		HTTPAddress:   valueOrDefault(lookup, "HTTP_ADDR", ":8080"),
		DatabaseURL:   valueOrDefault(lookup, "DATABASE_URL", ""),
		OIDCIssuerURL: valueOrDefault(lookup, "OIDC_ISSUER_URL", ""),
		OIDCClientID:  valueOrDefault(lookup, "OIDC_CLIENT_ID", ""),
	}
	return config, config.Validate()
}

func (c Config) Validate() error {
	if strings.TrimSpace(c.Environment) == "" {
		return fmt.Errorf("APP_ENV must not be empty")
	}
	if strings.TrimSpace(c.HTTPAddress) == "" {
		return fmt.Errorf("HTTP_ADDR must not be empty")
	}
	return nil
}

func valueOrDefault(lookup LookupEnv, key, fallback string) string {
	if value, ok := lookup(key); ok {
		return value
	}
	return fallback
}
