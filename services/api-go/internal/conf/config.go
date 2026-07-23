package conf

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

type LookupEnv func(string) (string, bool)

type Config struct {
	Environment                   string
	HTTPAddress                   string
	DatabaseURL                   string
	OIDCIssuerURL                 string
	OIDCClientID                  string
	OIDCClientSecret              string
	OIDCRedirectURL               string
	OIDCCenterClaim               string
	OIDCRolesClaim                string
	OIDCScopes                    []string
	SessionTTL                    time.Duration
	PublicAppURL                  string
	RabbitMQURL                   string
	RedisURL                      string
	InternalServiceToken          string
	PartnerScheduleURL            string
	NotificationWebhookURL        string
	PartnerScheduleCredential     string
	NotificationWebhookCredential string
	AIServiceURL                  string
}

func Load(lookup LookupEnv) (Config, error) {
	var loadErr error
	value := func(key, fallback string) string {
		if loadErr != nil {
			return ""
		}
		result, err := valueOrFile(lookup, key, fallback)
		if err != nil {
			loadErr = err
			return ""
		}
		return result
	}
	config := Config{
		Environment:                   value("APP_ENV", "development"),
		HTTPAddress:                   value("HTTP_ADDR", ":8080"),
		DatabaseURL:                   value("DATABASE_URL", ""),
		OIDCIssuerURL:                 value("OIDC_ISSUER_URL", ""),
		OIDCClientID:                  value("OIDC_CLIENT_ID", ""),
		OIDCClientSecret:              value("OIDC_CLIENT_SECRET", ""),
		OIDCRedirectURL:               value("OIDC_REDIRECT_URL", ""),
		OIDCCenterClaim:               value("OIDC_CENTER_CLAIM", "center_id"),
		OIDCRolesClaim:                value("OIDC_ROLES_CLAIM", "roles"),
		OIDCScopes:                    fieldsOrDefault(value("OIDC_SCOPES", "openid profile"), []string{"openid", "profile"}),
		SessionTTL:                    secondsOrDefault(value("SESSION_TTL_SECONDS", "28800"), 8*time.Hour),
		PublicAppURL:                  value("PUBLIC_APP_URL", ""),
		RabbitMQURL:                   value("RABBITMQ_URL", ""),
		RedisURL:                      value("REDIS_URL", ""),
		InternalServiceToken:          value("INTERNAL_SERVICE_TOKEN", ""),
		PartnerScheduleURL:            value("PARTNER_SCHEDULE_URL", ""),
		NotificationWebhookURL:        value("NOTIFICATION_WEBHOOK_URL", ""),
		PartnerScheduleCredential:     value("PARTNER_SCHEDULE_CREDENTIAL", ""),
		NotificationWebhookCredential: value("NOTIFICATION_WEBHOOK_CREDENTIAL", ""),
		AIServiceURL:                  value("AI_SERVICE_URL", ""),
	}
	if loadErr != nil {
		return Config{}, loadErr
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
	if c.SessionTTL <= 0 {
		return fmt.Errorf("SESSION_TTL_SECONDS must be positive")
	}
	if strings.EqualFold(c.Environment, "production") {
		for key, value := range map[string]string{
			"DATABASE_URL": c.DatabaseURL, "RABBITMQ_URL": c.RabbitMQURL, "REDIS_URL": c.RedisURL,
			"OIDC_ISSUER_URL": c.OIDCIssuerURL, "OIDC_CLIENT_ID": c.OIDCClientID, "OIDC_CLIENT_SECRET": c.OIDCClientSecret,
			"OIDC_REDIRECT_URL": c.OIDCRedirectURL, "PUBLIC_APP_URL": c.PublicAppURL, "INTERNAL_SERVICE_TOKEN": c.InternalServiceToken,
			"PARTNER_SCHEDULE_URL": c.PartnerScheduleURL, "PARTNER_SCHEDULE_CREDENTIAL": c.PartnerScheduleCredential,
			"NOTIFICATION_WEBHOOK_URL": c.NotificationWebhookURL, "NOTIFICATION_WEBHOOK_CREDENTIAL": c.NotificationWebhookCredential,
		} {
			if strings.TrimSpace(value) == "" {
				return fmt.Errorf("%s must not be empty in production", key)
			}
		}
		for key, value := range map[string]string{"OIDC_ISSUER_URL": c.OIDCIssuerURL, "OIDC_REDIRECT_URL": c.OIDCRedirectURL, "PUBLIC_APP_URL": c.PublicAppURL, "PARTNER_SCHEDULE_URL": c.PartnerScheduleURL, "NOTIFICATION_WEBHOOK_URL": c.NotificationWebhookURL} {
			if err := validateProductionURL(key, value); err != nil {
				return err
			}
		}
	}
	return nil
}

func valueOrFile(lookup LookupEnv, key, fallback string) (string, error) {
	if value, ok := lookup(key); ok {
		return value, nil
	}
	if path, ok := lookup(key + "_FILE"); ok && strings.TrimSpace(path) != "" {
		contents, err := os.ReadFile(strings.TrimSpace(path))
		if err != nil {
			return "", fmt.Errorf("read %s_FILE: %w", key, err)
		}
		return strings.TrimSpace(string(contents)), nil
	}
	return fallback, nil
}

func fieldsOrDefault(value string, fallback []string) []string {
	values := strings.Fields(value)
	if len(values) == 0 {
		return fallback
	}
	return values
}

func secondsOrDefault(value string, fallback time.Duration) time.Duration {
	seconds, err := strconv.ParseInt(strings.TrimSpace(value), 10, 64)
	if err != nil || seconds <= 0 {
		return 0
	}
	return time.Duration(seconds) * time.Second
}

func validateProductionURL(key, raw string) error {
	value, err := url.Parse(raw)
	if err != nil || value.Scheme != "https" || value.Host == "" {
		return fmt.Errorf("%s must be an HTTPS URL in production", key)
	}
	host := strings.ToLower(value.Hostname())
	if host == "localhost" || host == "ops-stub" || host == "127.0.0.1" || host == "::1" {
		return fmt.Errorf("%s must not target %s in production", key, host)
	}
	return nil
}
