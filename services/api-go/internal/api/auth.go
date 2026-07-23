package api

import (
	"net/http"
	"strings"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
)

type authHandler struct {
	authentication *services.Authentication
	secureCookie   bool
}

func mountAuthenticationRoutes(api *gin.RouterGroup, authentication *services.Authentication, secureCookie bool) {
	if authentication == nil {
		return
	}
	h := authHandler{authentication: authentication, secureCookie: secureCookie}
	api.GET("/auth/login", h.login)
	api.GET("/auth/callback", h.callback)
	api.GET("/auth/csrf", ActorMiddleware(authentication), h.csrf)
	api.POST("/auth/logout", ActorMiddleware(authentication), h.logout)
}

func (h authHandler) login(c *gin.Context) {
	returnTo := localReturnTo(c.Query("return_to"))
	if returnTo == "" {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-return-to", "请求无效", "return_to 必须是本站相对路径")
		return
	}
	redirect, err := h.authentication.Begin(c.Request.Context(), returnTo)
	if err != nil {
		writeProblem(c, http.StatusServiceUnavailable, "urn:problem:login-unavailable", "服务暂不可用", "暂时无法开始登录")
		return
	}
	c.Redirect(http.StatusFound, redirect)
}

func (h authHandler) callback(c *gin.Context) {
	state, code := strings.TrimSpace(c.Query("state")), strings.TrimSpace(c.Query("code"))
	if state == "" || code == "" {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-callback", "请求无效", "登录回调缺少必要参数")
		return
	}
	sessionID, returnTo, err := h.authentication.Complete(c.Request.Context(), state, code)
	if err != nil {
		// Keep provider error bodies and token details off the browser surface.
		c.Redirect(http.StatusFound, "/login?reason=callback_failed")
		return
	}
	h.setCookie(c, sessionID, 0)
	c.Redirect(http.StatusFound, returnTo)
}

func (h authHandler) csrf(c *gin.Context) {
	cookie, _ := c.Request.Cookie(SessionCookieName)
	value, err := h.authentication.CSRF(c.Request.Context(), cookie.Value)
	if err != nil {
		writeProblem(c, http.StatusServiceUnavailable, "urn:problem:session-unavailable", "服务暂不可用", "登录会话暂时无法验证")
		return
	}
	c.JSON(http.StatusOK, gin.H{"csrf_token": value})
}

func (h authHandler) logout(c *gin.Context) {
	cookie, _ := c.Request.Cookie(SessionCookieName)
	if err := h.authentication.Logout(c.Request.Context(), cookie.Value); err != nil {
		writeProblem(c, http.StatusServiceUnavailable, "urn:problem:session-unavailable", "服务暂不可用", "登录会话暂时无法注销")
		return
	}
	h.setCookie(c, "", -1)
	c.Status(http.StatusNoContent)
}

func (h authHandler) setCookie(c *gin.Context, value string, maxAge int) {
	http.SetCookie(c.Writer, &http.Cookie{Name: SessionCookieName, Value: value, Path: "/", MaxAge: maxAge, Secure: h.secureCookie, HttpOnly: true, SameSite: http.SameSiteLaxMode})
}

func localReturnTo(value string) string {
	if value == "" {
		return "/"
	}
	if !strings.HasPrefix(value, "/") || strings.HasPrefix(value, "//") || strings.Contains(value, "\\") || strings.ContainsAny(value, "\r\n\x00") {
		return ""
	}
	return value
}
