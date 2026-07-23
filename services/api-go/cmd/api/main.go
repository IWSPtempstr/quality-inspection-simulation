package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/ai"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/oidc"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/rabbitmq"
	redisclient "github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/redis"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/conf"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/core"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
)

func main() {
	config, err := conf.Load(os.LookupEnv)
	if err != nil {
		slog.Error("invalid configuration", "error", err)
		os.Exit(1)
	}

	logger := core.NewLogger(config.Environment)
	db, err := postgres.Open(context.Background(), config.DatabaseURL)
	if err != nil {
		logger.Error("initialize PostgreSQL", "error", err)
		os.Exit(1)
	}
	sqlDB, err := db.DB()
	if err != nil {
		logger.Error("access PostgreSQL", "error", err)
		os.Exit(1)
	}
	defer func() { _ = sqlDB.Close() }()
	approvalLocks, err := redisclient.Open(config.RedisURL)
	if err != nil {
		logger.Error("initialize Redis", "error", err)
		os.Exit(1)
	}
	defer func() { _ = approvalLocks.Close() }()
	broker, err := rabbitmq.Open(config.RabbitMQURL)
	if err != nil {
		logger.Error("initialize RabbitMQ", "error", err)
		os.Exit(1)
	}
	defer func() { _ = broker.Close() }()
	oidcClient, err := oidc.NewClient(context.Background(), config.OIDCIssuerURL, config.OIDCClientID, config.OIDCClientSecret, config.OIDCRedirectURL, config.OIDCCenterClaim, config.OIDCRolesClaim, config.OIDCScopes)
	if err != nil {
		logger.Error("initialize OIDC verifier", "error", err)
		os.Exit(1)
	}
	server := &http.Server{
		Addr: config.HTTPAddress,
		Handler: api.NewRouterWithG8AndAuthentication(logger, db, approvalLocks, config.InternalServiceToken, api.HealthProbes{
			Postgres:     api.HealthProbeFunc(func(ctx context.Context) error { return db.WithContext(ctx).Exec("SELECT 1").Error }),
			RabbitMQ:     api.HealthProbeFunc(broker.Ping),
			Redis:        api.HealthProbeFunc(approvalLocks.Ping),
			Partner:      api.HTTPReachabilityProbe{URL: config.PartnerScheduleURL},
			Notification: api.HTTPReachabilityProbe{URL: config.NotificationWebhookURL},
		}, ai.New(config.AIServiceURL, config.InternalServiceToken), services.NewAuthentication(approvalLocks, oidcClient, config.SessionTTL), config.Environment == "production"),
		ReadHeaderTimeout: 5 * time.Second,
	}

	if err := core.Serve(context.Background(), server, logger); err != nil {
		logger.Error("api server stopped unexpectedly", "error", err)
		os.Exit(1)
	}
}
