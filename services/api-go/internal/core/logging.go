package core

import (
	"io"
	"log/slog"
	"os"
)

func NewLogger(environment string) *slog.Logger {
	return slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: logLevel(environment)}))
}

func NewLogWriter(logger *slog.Logger) io.Writer {
	return logWriter{logger: logger}
}

func logLevel(environment string) slog.Level {
	if environment == "development" {
		return slog.LevelDebug
	}
	return slog.LevelInfo
}

type logWriter struct {
	logger *slog.Logger
}

func (w logWriter) Write(data []byte) (int, error) {
	w.logger.Info("http request", "message", string(data))
	return len(data), nil
}
