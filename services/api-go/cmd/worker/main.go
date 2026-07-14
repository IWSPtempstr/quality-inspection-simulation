package main

import (
	"log/slog"
	"os"

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
	logger.Info("worker started", "mode", "idle")
	if err := core.WaitForShutdown(); err != nil {
		logger.Error("worker stopped unexpectedly", "error", err)
		os.Exit(1)
	}
}
