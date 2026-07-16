package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
	"io"
	"net/http"
	"strings"
)

type g6Handler struct {
	db           *gorm.DB
	schedules    services.ScheduleService
	serviceToken string
}

func mountG6Routes(api, root *gin.RouterGroup, authenticator Authenticator, db *gorm.DB, locks services.ApprovalLocker, serviceToken string) {
	h := g6Handler{db: db, schedules: services.NewScheduleService(db, locks), serviceToken: serviceToken}
	auth := ActorMiddleware(authenticator)
	read := RequireCapability(entities.CapabilityScheduleRead)
	write := RequireCapability(entities.CapabilityScheduleWrite)
	api.POST("/schedule-previews", auth, write, RequireIdempotencyKey(), h.create)
	api.GET("/schedule-previews/:preview_id", auth, read, h.get)
	api.POST("/schedule-previews/:preview_id/approve", auth, write, RequireIdempotencyKey(), RequireVersion(), h.approve)
	api.POST("/schedule-previews/:preview_id/reject", auth, write, RequireIdempotencyKey(), RequireVersion(), h.reject)
	internal := root.Group("/internal/v1")
	internal.POST("/schedule-previews/:preview_id/candidate", h.internalAuth, h.candidate)
}
func (h g6Handler) internalAuth(c *gin.Context) {
	if h.serviceToken == "" || c.GetHeader("X-Internal-Service-Token") != h.serviceToken {
		writeProblem(c, http.StatusUnauthorized, "urn:problem:unauthorized", "未认证", "需要有效服务凭据")
		return
	}
	c.Next()
}
func (h g6Handler) create(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	h.mutate(c, actor, "create_schedule_preview", "schedule-previews", http.StatusCreated, func(s services.ScheduleService) (entities.SchedulePreview, error) {
		return s.Create(c.Request.Context(), actor)
	})
}
func (h g6Handler) get(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	p, err := h.schedules.Get(c, actor, c.Param("preview_id"))
	if err != nil {
		writeG6Error(c, err)
		return
	}
	c.JSON(http.StatusOK, previewJSON(p))
}
func (h g6Handler) approve(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	id := c.Param("preview_id")
	h.mutate(c, actor, "approve_schedule_preview", id, http.StatusOK, func(s services.ScheduleService) (entities.SchedulePreview, error) {
		return s.Approve(c.Request.Context(), actor, id, mustVersion(c))
	})
}
func (h g6Handler) reject(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	id := c.Param("preview_id")
	h.mutate(c, actor, "reject_schedule_preview", id, http.StatusOK, func(s services.ScheduleService) (entities.SchedulePreview, error) {
		return s.Reject(c.Request.Context(), actor, id, mustVersion(c))
	})
}
func (h g6Handler) candidate(c *gin.Context) {
	var input struct {
		SnapshotID      string          `json:"snapshot_id"`
		InputHash       string          `json:"input_hash"`
		Version         int64           `json:"version"`
		Candidate       json.RawMessage `json:"candidate"`
		NormalizedSteps json.RawMessage `json:"normalized_steps"`
	}
	if err := c.ShouldBindJSON(&input); err != nil {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "候选结果无效")
		return
	}
	p, err := h.schedules.Candidate(c, c.Param("preview_id"), input.SnapshotID, input.InputHash, input.Version, input.Candidate, input.NormalizedSteps)
	if err != nil {
		writeG6Error(c, err)
		return
	}
	c.JSON(http.StatusOK, previewJSON(p))
}

// mutate persists the exact first HTTP response with the domain mutation so
// retries cannot repeat a preview lifecycle transition.
func (h g6Handler) mutate(c *gin.Context, actor entities.Actor, operation, aggregateID string, success int, work func(services.ScheduleService) (entities.SchedulePreview, error)) {
	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "无法读取请求体")
		return
	}
	key := c.GetHeader("Idempotency-Key")
	scope := strings.Join([]string{actor.CenterID, actor.ID, operation, aggregateID}, ":")
	repository := repositories.IdempotencyRepository{}
	if record, found, findErr := repository.Find(c.Request.Context(), h.db, scope, key); findErr != nil {
		writeG6Error(c, findErr)
		return
	} else if found {
		if record.RequestHash != g6RequestHash(body) {
			writeProblem(c, http.StatusConflict, "urn:problem:idempotency-conflict", "请求冲突", "幂等键已用于不同请求")
			return
		}
		if record.CompletedAt != nil && record.ResponseStatus != nil {
			c.Data(*record.ResponseStatus, valueOrJSON(record.ResponseContentType), record.ResponseBody)
			return
		}
		writeProblem(c, http.StatusConflict, "urn:problem:idempotency-in-progress", "请求冲突", "相同请求正在处理")
		return
	}

	contentType := "application/json; charset=utf-8"
	var response []byte
	err = h.db.WithContext(c.Request.Context()).Transaction(func(tx *gorm.DB) error {
		if registerErr := (services.IdempotencyService{}).Register(c.Request.Context(), tx, scope, key, body); registerErr != nil {
			return registerErr
		}
		preview, workErr := work(services.NewScheduleService(tx, h.schedules.Locks()))
		if workErr != nil {
			return workErr
		}
		response, workErr = json.Marshal(previewJSON(preview))
		if workErr != nil {
			return workErr
		}
		record, found, findErr := repository.Find(c.Request.Context(), tx, scope, key)
		if findErr != nil || !found {
			return fmt.Errorf("find claimed idempotency record: %w", findErr)
		}
		return repository.Complete(c.Request.Context(), tx, record.ID, success, contentType, response)
	})
	if err != nil {
		if errors.Is(err, entities.ErrIdempotencyReplay) {
			writeProblem(c, http.StatusConflict, "urn:problem:idempotency-in-progress", "请求冲突", "相同请求正在处理")
			return
		}
		writeG6Error(c, err)
		return
	}
	c.Data(success, contentType, response)
}

func g6RequestHash(body []byte) string { return services.RequestHash(body) }
func mustVersion(c *gin.Context) int64 { v, _ := ExpectedVersion(c); return v }
func previewJSON(p entities.SchedulePreview) gin.H {
	return gin.H{"id": p.ID, "status": p.Status, "snapshot_id": p.SnapshotID, "version": p.Version, "candidate": json.RawMessage(p.Candidate), "schedule_steps": json.RawMessage(p.NormalizedSteps)}
}
func writeG6Error(c *gin.Context, err error) {
	switch {
	case errors.Is(err, services.ErrApprovalLockUnavailable):
		writeProblem(c, http.StatusServiceUnavailable, "urn:problem:service-degraded", "服务降级", "审批锁不可用")
	case errors.Is(err, entities.ErrVersionConflict):
		writeProblem(c, http.StatusConflict, "urn:problem:version-conflict", "版本冲突", "资源已更新")
	case errors.Is(err, services.ErrInvalidPreviewTransition):
		writeProblem(c, http.StatusConflict, "urn:problem:invalid-transition", "状态冲突", "预览状态不允许该操作")
	case strings.Contains(err.Error(), "record not found"):
		writeProblem(c, http.StatusNotFound, "urn:problem:not-found", "未找到", "预览不存在")
	default:
		writeProblem(c, http.StatusInternalServerError, "urn:problem:internal", "内部错误", "处理预览失败")
	}
}
