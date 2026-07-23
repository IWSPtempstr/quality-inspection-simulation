package api

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api/generated"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/core"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type readinessResponse struct {
	Status string `json:"status"`
}

func NewRouter(logger *slog.Logger, authenticators ...Authenticator) *gin.Engine {
	return newRouter(logger, nil, nil, "", HealthProbes{}, authenticators...)
}

// NewRouterWithDatabase mounts the G4 public operations against the configured
// PostgreSQL connection. The database-free constructor remains useful for
// health and authentication tests.
func NewRouterWithDatabase(logger *slog.Logger, db *gorm.DB, authenticators ...Authenticator) *gin.Engine {
	return newRouter(logger, db, nil, "", HealthProbes{Postgres: gormHealthProbe{db: db}}, authenticators...)
}

// NewRouterWithScheduling mounts G6 routes with its Redis approval lock and
// service credential for the controlled internal candidate callback.
func NewRouterWithScheduling(logger *slog.Logger, db *gorm.DB, locks services.ApprovalLocker, serviceToken string, authenticators ...Authenticator) *gin.Engine {
	return newRouter(logger, db, locks, serviceToken, HealthProbes{Postgres: gormHealthProbe{db: db}}, authenticators...)
}

// NewRouterWithOperations mounts G4-G7 using independently injected health
// probes. Production wiring owns concrete infrastructure clients; tests can
// exercise every outage without exposing dependency details to HTTP callers.
func NewRouterWithOperations(logger *slog.Logger, db *gorm.DB, locks services.ApprovalLocker, serviceToken string, probes HealthProbes, authenticators ...Authenticator) *gin.Engine {
	if probes.Postgres == nil {
		probes.Postgres = gormHealthProbe{db: db}
	}
	return newRouter(logger, db, locks, serviceToken, probes, authenticators...)
}

// NewRouterWithG8 mounts the bounded G8 public facade. The injected client is
// restricted to fixed A8 endpoints; callers never receive an AI service URL.
func NewRouterWithG8(logger *slog.Logger, db *gorm.DB, locks services.ApprovalLocker, serviceToken string, probes HealthProbes, assistance services.AssistanceClient, authenticators ...Authenticator) *gin.Engine {
	if probes.Postgres == nil {
		probes.Postgres = gormHealthProbe{db: db}
	}
	return newRouterWithG8(logger, db, locks, serviceToken, probes, assistance, authenticators...)
}

// NewRouterWithG8AndAuthentication installs the I7 opaque BFF-session flow.
// Existing constructors remain for bounded legacy and integration test setup.
func NewRouterWithG8AndAuthentication(logger *slog.Logger, db *gorm.DB, locks services.ApprovalLocker, serviceToken string, probes HealthProbes, assistance services.AssistanceClient, authentication *services.Authentication, secureCookie bool) *gin.Engine {
	if probes.Postgres == nil {
		probes.Postgres = gormHealthProbe{db: db}
	}
	return newRouterWithAuthentication(logger, db, locks, serviceToken, probes, assistance, authentication, secureCookie)
}

func newRouter(logger *slog.Logger, db *gorm.DB, locks services.ApprovalLocker, serviceToken string, probes HealthProbes, authenticators ...Authenticator) *gin.Engine {
	return newRouterWithG8(logger, db, locks, serviceToken, probes, nil, authenticators...)
}

func newRouterWithG8(logger *slog.Logger, db *gorm.DB, locks services.ApprovalLocker, serviceToken string, probes HealthProbes, assistance services.AssistanceClient, authenticators ...Authenticator) *gin.Engine {
	var authenticator Authenticator = AuthenticatorFunc(rejectAuthenticator)
	if len(authenticators) > 0 && authenticators[0] != nil {
		authenticator = authenticators[0]
	}
	return buildRouter(logger, db, locks, serviceToken, probes, assistance, authenticator, nil, false)
}

func newRouterWithAuthentication(logger *slog.Logger, db *gorm.DB, locks services.ApprovalLocker, serviceToken string, probes HealthProbes, assistance services.AssistanceClient, authentication *services.Authentication, secureCookie bool) *gin.Engine {
	return buildRouter(logger, db, locks, serviceToken, probes, assistance, authentication, authentication, secureCookie)
}

func buildRouter(logger *slog.Logger, db *gorm.DB, locks services.ApprovalLocker, serviceToken string, probes HealthProbes, assistance services.AssistanceClient, authenticator Authenticator, authentication *services.Authentication, secureCookie bool) *gin.Engine {
	router := gin.New()
	router.Use(core.CorrelationMiddleware(), gin.LoggerWithConfig(gin.LoggerConfig{Output: core.NewLogWriter(logger)}), gin.Recovery())

	api := router.Group("/api/v1")
	api.GET("/system/health", probes.handler())
	api.Use(CSRFProtection(authenticator))
	mountAuthenticationRoutes(api, authentication, secureCookie)
	api.GET("/session/me", ActorMiddleware(authenticator), session)
	if db != nil {
		mountG4Routes(api, authenticator, db)
		mountG6Routes(api, router.Group(""), authenticator, db, locks, serviceToken)
		mountG7Routes(api, authenticator, db)
		mountG8Routes(api, authenticator, db, assistance, serviceToken)
	}
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

type gormHealthProbe struct{ db *gorm.DB }

func (p gormHealthProbe) Probe(ctx context.Context) error {
	if p.db == nil {
		return nil
	}
	return p.db.WithContext(ctx).Exec("SELECT 1").Error
}

func ready(c *gin.Context) {
	c.JSON(http.StatusOK, readinessResponse{Status: "ready"})
}
