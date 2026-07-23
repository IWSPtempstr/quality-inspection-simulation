package api

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
)

const (
	SessionCookieName = "__Host-public_session"
	actorContextKey   = "authenticated_actor"
	versionContextKey = "if_match_version"
)

type Authenticator interface {
	Authenticate(context.Context, string) (entities.Actor, error)
}

type AuthenticatorFunc func(context.Context, string) (entities.Actor, error)

func (fn AuthenticatorFunc) Authenticate(ctx context.Context, session string) (entities.Actor, error) {
	return fn(ctx, session)
}

func rejectAuthenticator(context.Context, string) (entities.Actor, error) {
	return entities.Actor{}, entities.ErrUnauthenticated
}

func ActorMiddleware(authenticator Authenticator) gin.HandlerFunc {
	return func(c *gin.Context) {
		cookie, err := c.Request.Cookie(SessionCookieName)
		if err != nil || strings.TrimSpace(cookie.Value) == "" {
			writeProblem(c, http.StatusUnauthorized, "urn:problem:unauthorized", "未认证", "需要有效的登录会话")
			return
		}
		actor, err := authenticator.Authenticate(c.Request.Context(), cookie.Value)
		if err != nil {
			if errors.Is(err, services.ErrSessionUnavailable) {
				writeProblem(c, http.StatusServiceUnavailable, "urn:problem:session-unavailable", "服务暂不可用", "登录会话暂时无法验证")
				return
			}
			writeProblem(c, http.StatusUnauthorized, "urn:problem:unauthorized", "未认证", "登录会话无效或已过期")
			return
		}
		c.Set(actorContextKey, actor)
		c.Next()
	}
}

type CSRFValidator interface {
	ValidateCSRF(context.Context, string, string) error
}

// CSRFProtection applies only when the configured authenticator owns a BFF
// session. Legacy injected authenticators remain useful for focused route tests.
func CSRFProtection(authenticator Authenticator) gin.HandlerFunc {
	validator, ok := authenticator.(CSRFValidator)
	if !ok {
		return func(c *gin.Context) { c.Next() }
	}
	return func(c *gin.Context) {
		switch c.Request.Method {
		case http.MethodGet, http.MethodHead, http.MethodOptions:
			c.Next()
			return
		}
		cookie, err := c.Request.Cookie(SessionCookieName)
		if err != nil || strings.TrimSpace(cookie.Value) == "" {
			c.Next()
			return
		}
		if err := validator.ValidateCSRF(c.Request.Context(), cookie.Value, c.GetHeader("X-CSRF-Token")); err != nil {
			if errors.Is(err, services.ErrSessionUnavailable) {
				writeProblem(c, http.StatusServiceUnavailable, "urn:problem:session-unavailable", "服务暂不可用", "登录会话暂时无法验证")
				return
			}
			writeProblem(c, http.StatusForbidden, "urn:problem:csrf", "请求被拒绝", "CSRF 令牌无效或缺失")
			return
		}
		c.Next()
	}
}

func RequireCapability(capability entities.Capability) gin.HandlerFunc {
	return func(c *gin.Context) {
		actor, ok := ActorFromContext(c)
		if !ok {
			writeProblem(c, http.StatusUnauthorized, "urn:problem:unauthorized", "未认证", "需要有效的登录会话")
			return
		}
		if err := services.Authorize(actor, capability); err != nil {
			writeProblem(c, http.StatusForbidden, "urn:problem:forbidden", "无权限", "当前角色无权执行该操作")
			return
		}
		c.Next()
	}
}

func RequireIdempotencyKey() gin.HandlerFunc {
	return func(c *gin.Context) {
		if strings.TrimSpace(c.GetHeader("Idempotency-Key")) == "" {
			writeProblem(c, http.StatusBadRequest, "urn:problem:missing-idempotency-key", "请求无效", "写请求必须提供 Idempotency-Key")
			return
		}
		c.Next()
	}
}

func RequireVersion() gin.HandlerFunc {
	return func(c *gin.Context) {
		value, err := strconv.ParseInt(strings.Trim(strings.TrimSpace(c.GetHeader("If-Match")), "\""), 10, 64)
		if err != nil || value < 0 {
			writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-if-match", "请求无效", "更新请求必须提供整数 If-Match 版本")
			return
		}
		c.Set(versionContextKey, value)
		c.Next()
	}
}

func ActorFromContext(c *gin.Context) (entities.Actor, bool) {
	actor, ok := c.Get(actorContextKey)
	if !ok {
		return entities.Actor{}, false
	}
	value, ok := actor.(entities.Actor)
	return value, ok
}

func ExpectedVersion(c *gin.Context) (int64, bool) {
	value, ok := c.Get(versionContextKey)
	version, isVersion := value.(int64)
	return version, ok && isVersion
}

func writeProblem(c *gin.Context, status int, problemType, title, detail string) {
	c.Header("Content-Type", "application/problem+json; charset=utf-8")
	c.AbortWithStatusJSON(status, gin.H{"type": problemType, "title": title, "status": status, "detail": detail, "instance": c.Request.URL.Path})
}
