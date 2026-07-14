package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/oidc"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/conf"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/core"
)

func main() {
	config, err := conf.Load(os.LookupEnv)
	if err != nil {
		slog.Error("invalid configuration", "error", err)
		os.Exit(1)
	}

	logger := core.NewLogger(config.Environment)
	authenticator, err := oidc.NewVerifier(context.Background(), config.OIDCIssuerURL, config.OIDCClientID)
	if err != nil {
		logger.Error("initialize OIDC verifier", "error", err)
		os.Exit(1)
	}
	server := &http.Server{
		Addr:              config.HTTPAddress,
		Handler:           api.NewRouter(logger, authenticator),
		ReadHeaderTimeout: 5 * time.Second,
	}

	if err := core.Serve(context.Background(), server, logger); err != nil {
		logger.Error("api server stopped unexpectedly", "error", err)
		os.Exit(1)
	}
}
