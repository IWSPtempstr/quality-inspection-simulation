package api

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type g7Handler struct {
	db        *gorm.DB
	execution services.ExecutionService
}

func mountG7Routes(api *gin.RouterGroup, authenticator Authenticator, db *gorm.DB) {
	h := g7Handler{db: db, execution: services.NewExecutionService(db)}
	auth := ActorMiddleware(authenticator)
	exec := RequireCapability(entities.CapabilityExecutionWrite)
	eventsRead := RequireCapability(entities.CapabilityEventsRead)
	eventsWrite := RequireCapability(entities.CapabilityEventsWrite)
	notifications := RequireCapability(entities.CapabilityNotificationsRead)
	api.PATCH("/schedule-steps/:step_id/start", auth, exec, RequireIdempotencyKey(), RequireVersion(), h.start)
	api.PATCH("/schedule-steps/:step_id/complete", auth, exec, RequireIdempotencyKey(), RequireVersion(), h.complete)
	api.GET("/events", auth, eventsRead, h.events)
	api.GET("/events/:event_id", auth, eventsRead, h.event)
	api.POST("/events/:event_id/acknowledge", auth, eventsWrite, RequireIdempotencyKey(), RequireVersion(), h.acknowledge)
	api.POST("/events/:event_id/close", auth, eventsWrite, RequireIdempotencyKey(), RequireVersion(), h.close)
	api.GET("/notifications", auth, notifications, h.notifications)
	api.PATCH("/notifications/:notification_id/read", auth, notifications, RequireIdempotencyKey(), h.read)
}
func (h g7Handler) start(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	h.mutate(c, actor, "start_schedule_step", c.Param("step_id"), http.StatusOK, func(tx *gorm.DB) (any, error) {
		return services.NewExecutionService(tx).Start(c, actor, c.Param("step_id"), mustVersion(c))
	})
}
func (h g7Handler) complete(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	body, _ := io.ReadAll(c.Request.Body)
	var in struct {
		ProjectResult json.RawMessage `json:"project_result"`
	}
	if len(body) > 0 && json.Unmarshal(body, &in) != nil {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "检测结果无效")
		return
	}
	c.Request.Body = io.NopCloser(strings.NewReader(string(body)))
	h.mutate(c, actor, "complete_schedule_step", c.Param("step_id"), http.StatusOK, func(tx *gorm.DB) (any, error) {
		return services.NewExecutionService(tx).Complete(c, actor, c.Param("step_id"), mustVersion(c), in.ProjectResult)
	})
}
func (h g7Handler) acknowledge(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	h.mutate(c, actor, "acknowledge_event", c.Param("event_id"), http.StatusOK, func(tx *gorm.DB) (any, error) {
		return services.NewExecutionService(tx).AcknowledgeEvent(c, actor, c.Param("event_id"), mustVersion(c))
	})
}
func (h g7Handler) close(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	body, _ := io.ReadAll(c.Request.Body)
	var in struct {
		Disposition string `json:"disposition"`
	}
	if len(body) > 0 && json.Unmarshal(body, &in) != nil {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "事件处置无效")
		return
	}
	if strings.TrimSpace(in.Disposition) == "" {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "事件处置不能为空")
		return
	}
	c.Request.Body = io.NopCloser(strings.NewReader(string(body)))
	h.mutate(c, actor, "close_event", c.Param("event_id"), http.StatusOK, func(tx *gorm.DB) (any, error) {
		return services.NewExecutionService(tx).CloseEvent(c, actor, c.Param("event_id"), mustVersion(c), in.Disposition)
	})
}
func (h g7Handler) events(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	items, err := h.execution.Events(c, actor)
	if err != nil {
		writeG7Error(c, err)
		return
	}
	out := make([]gin.H, 0, len(items))
	for _, e := range items {
		out = append(out, eventJSON(e))
	}
	c.JSON(http.StatusOK, gin.H{"items": out, "page": 1, "page_size": len(out), "total": len(out)})
}
func (h g7Handler) event(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	e, err := h.execution.Event(c, actor, c.Param("event_id"))
	if err != nil {
		writeG7Error(c, err)
		return
	}
	c.JSON(http.StatusOK, eventJSON(e))
}
func (h g7Handler) notifications(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	items, err := h.execution.Notifications(c, actor)
	if err != nil {
		writeG7Error(c, err)
		return
	}
	out := make([]gin.H, 0, len(items))
	for _, n := range items {
		out = append(out, notificationJSON(n))
	}
	c.JSON(http.StatusOK, gin.H{"items": out, "page": 1, "page_size": len(out), "total": len(out)})
}
func (h g7Handler) read(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	h.mutate(c, actor, "read_notification", c.Param("notification_id"), http.StatusNoContent, func(tx *gorm.DB) (any, error) {
		return map[string]any{}, services.NewExecutionService(tx).MarkRead(c, actor, c.Param("notification_id"))
	})
}
func (h g7Handler) mutate(c *gin.Context, actor entities.Actor, op, id string, status int, work func(*gorm.DB) (any, error)) {
	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "无法读取请求体")
		return
	}
	key := c.GetHeader("Idempotency-Key")
	scope := strings.Join([]string{actor.CenterID, actor.ID, op, id}, ":")
	repo := repositories.IdempotencyRepository{}
	if r, found, e := repo.Find(c, h.db, scope, key); e != nil {
		writeG7Error(c, e)
		return
	} else if found {
		if r.RequestHash != services.RequestHash(body) {
			writeProblem(c, http.StatusConflict, "urn:problem:idempotency-conflict", "请求冲突", "幂等键已用于不同请求")
			return
		}
		if r.CompletedAt != nil && r.ResponseStatus != nil {
			c.Data(*r.ResponseStatus, valueOrJSON(r.ResponseContentType), r.ResponseBody)
			return
		}
		writeProblem(c, http.StatusConflict, "urn:problem:idempotency-in-progress", "请求冲突", "相同请求正在处理")
		return
	}
	var response []byte
	err = h.db.WithContext(c).Transaction(func(tx *gorm.DB) error {
		if e := (services.IdempotencyService{}).Register(c, tx, scope, key, body); e != nil {
			return e
		}
		v, e := work(tx)
		if e != nil {
			return e
		}
		response, e = json.Marshal(g7JSON(v))
		if e != nil {
			return e
		}
		r, found, e := repo.Find(c, tx, scope, key)
		if e != nil || !found {
			return e
		}
		return repo.Complete(c, tx, r.ID, status, "application/json; charset=utf-8", response)
	})
	if err != nil {
		if errors.Is(err, entities.ErrIdempotencyReplay) {
			writeProblem(c, http.StatusConflict, "urn:problem:idempotency-in-progress", "请求冲突", "相同请求正在处理")
			return
		}
		writeG7Error(c, err)
		return
	}
	c.Data(status, "application/json; charset=utf-8", response)
}
func eventJSON(e entities.SystemEvent) gin.H {
	return gin.H{"id": e.ID, "event_type": e.EventType, "entity_type": e.EntityType, "severity": e.Severity, "entity_id": e.EntityID, "status": e.Status, "version": e.Version, "occurred_at": e.OccurredAt, "payload": json.RawMessage(e.Payload)}
}
func notificationJSON(n entities.Notification) gin.H {
	return gin.H{"id": n.ID, "title": n.Title, "status": n.Status, "created_at": n.CreatedAt}
}
func g7JSON(v any) any {
	switch x := v.(type) {
	case entities.ScheduleStep:
		return gin.H{"id": x.ID, "order_id": x.OrderID, "project_id": x.ProjectID, "starts_at": x.StartsAt, "ends_at": x.EndsAt, "status": x.Status, "frozen": x.Status == "running", "version": x.Version}
	case entities.SystemEvent:
		return eventJSON(x)
	default:
		return v
	}
}
func writeG7Error(c *gin.Context, err error) {
	switch {
	case errors.Is(err, entities.ErrVersionConflict):
		writeProblem(c, http.StatusConflict, "urn:problem:version-conflict", "版本冲突", "资源已更新")
	case errors.Is(err, services.ErrInvalidOpaqueReference):
		writeProblem(c, http.StatusConflict, "urn:problem:invalid-reference", "请求冲突", "候选或草稿引用已失效")
	case errors.Is(err, services.ErrInvalidExecutionTransition), errors.Is(err, services.ErrInvalidEventTransition):
		writeProblem(c, http.StatusConflict, "urn:problem:invalid-transition", "状态冲突", "状态不允许该操作")
	case errors.Is(err, gorm.ErrRecordNotFound):
		writeProblem(c, http.StatusNotFound, "urn:problem:not-found", "未找到", "资源不存在")
	default:
		writeProblem(c, http.StatusInternalServerError, "urn:problem:internal", "内部错误", "处理请求失败")
	}
}
