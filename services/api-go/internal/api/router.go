package api

import (
	"log/slog"
	"net/http"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api/generated"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/core"
	"github.com/gin-gonic/gin"
)

type readinessResponse struct {
	Status string `json:"status"`
}

func NewRouter(logger *slog.Logger) *gin.Engine {
	router := gin.New()
	router.Use(core.CorrelationMiddleware(), gin.LoggerWithConfig(gin.LoggerConfig{Output: core.NewLogWriter(logger)}), gin.Recovery())

	api := router.Group("/api/v1")
	api.GET("/system/health", health)
	router.GET("/readyz", ready)

	return router
}

func health(c *gin.Context) {
	c.JSON(http.StatusOK, generated.Health{
		Status:   "healthy",
		Services: map[string]string{"api": "available"},
	})
}

func ready(c *gin.Context) {
	c.JSON(http.StatusOK, readinessResponse{Status: "ready"})
}
