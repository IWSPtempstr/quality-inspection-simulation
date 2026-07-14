package api

import (
	"log/slog"
	"net/http"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api/generated"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/core"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
)

type readinessResponse struct {
	Status string `json:"status"`
}

func NewRouter(logger *slog.Logger, authenticators ...Authenticator) *gin.Engine {
	router := gin.New()
	router.Use(core.CorrelationMiddleware(), gin.LoggerWithConfig(gin.LoggerConfig{Output: core.NewLogWriter(logger)}), gin.Recovery())

	api := router.Group("/api/v1")
	api.GET("/system/health", health)
	var authenticator Authenticator = AuthenticatorFunc(rejectAuthenticator)
	if len(authenticators) > 0 && authenticators[0] != nil {
		authenticator = authenticators[0]
	}
	api.GET("/session/me", ActorMiddleware(authenticator), session)
	router.GET("/readyz", ready)

	return router
}

func session(c *gin.Context) {
	actor, ok := ActorFromContext(c)
	if !ok {
		writeProblem(c, http.StatusUnauthorized, "urn:problem:unauthorized", "未认证", "需要有效的登录会话")
		return
	}
	role, err := services.PrimaryRole(actor)
	if err != nil {
		writeProblem(c, http.StatusForbidden, "urn:problem:forbidden", "无权限", "登录会话不含有效角色")
		return
	}
	c.JSON(http.StatusOK, generated.Session{UserId: actor.ID, Role: string(role), DisplayName: actor.DisplayName})
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
