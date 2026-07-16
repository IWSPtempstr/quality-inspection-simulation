package api

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type g8Handler struct {
	db      *gorm.DB
	service services.G8Service
}

func mountG8Routes(api *gin.RouterGroup, authenticator Authenticator, db *gorm.DB, assistance services.AssistanceClient, serviceToken string) {
	h := g8Handler{db: db, service: services.NewG8Service(db, assistance, services.NewOpaqueReferenceSigner(serviceToken))}
	auth := ActorMiddleware(authenticator)
	scheduleRead, scheduleWrite := RequireCapability(entities.CapabilityScheduleRead), RequireCapability(entities.CapabilityScheduleWrite)
	eventsRead, eventsWrite := RequireCapability(entities.CapabilityEventsRead), RequireCapability(entities.CapabilityEventsWrite)
	notifySend, auditRead := RequireCapability(entities.CapabilityNotificationsSend), RequireCapability(entities.CapabilityAuditRead)
	api.POST("/events/:event_id/diagnose", auth, eventsRead, h.diagnose)
	api.POST("/schedule-previews/:preview_id/explanation", auth, scheduleRead, h.explain)
	api.POST("/schedule-previews/preflight", auth, scheduleWrite, h.preflight)
	api.POST("/events/:event_id/case-candidates", auth, eventsWrite, h.candidate)
	api.POST("/exception-case-candidates/:candidate_id/submit", auth, eventsWrite, RequireIdempotencyKey(), RequireVersion(), h.submitCase)
	api.POST("/audit-logs/filter-suggestions", auth, auditRead, h.auditFilters)
	api.POST("/notification-drafts", auth, notifySend, h.draftNotification)
	api.POST("/notification-drafts/:draft_id/send", auth, notifySend, RequireIdempotencyKey(), RequireVersion(), h.sendDraft)
}

func (h g8Handler) diagnose(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	value, err := h.service.Diagnose(c, actor, c.Param("event_id"))
	if err != nil {
		writeG8Error(c, err)
		return
	}
	c.JSON(http.StatusOK, value)
}
func (h g8Handler) explain(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	var input struct {
		SubjectType string `json:"subject_type"`
		SubjectID   string `json:"subject_id"`
	}
	if c.ShouldBindJSON(&input) != nil || !validSubject(input.SubjectType) || strings.TrimSpace(input.SubjectID) == "" {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "解释对象无效")
		return
	}
	value, err := h.service.Explain(c, actor, c.Param("preview_id"), input.SubjectType, input.SubjectID)
	if err != nil {
		writeG8Error(c, err)
		return
	}
	c.JSON(http.StatusOK, value)
}
func validSubject(value string) bool {
	return value == "preview" || value == "order" || value == "step"
}
func (h g8Handler) preflight(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	var input struct {
		Scope       string   `json:"scope"`
		OrderID     string   `json:"order_id"`
		PreviewID   string   `json:"preview_id"`
		ResourceIDs []string `json:"resource_ids"`
	}
	if c.ShouldBindJSON(&input) != nil {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "预检请求无效")
		return
	}
	value, err := h.service.Preflight(c, actor, input.Scope, input.OrderID, input.PreviewID, input.ResourceIDs)
	if err != nil {
		writeG8Error(c, err)
		return
	}
	c.JSON(http.StatusOK, value)
}
func (h g8Handler) candidate(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	value, err := h.service.Candidate(c, actor, c.Param("event_id"))
	if err != nil {
		writeG8Error(c, err)
		return
	}
	c.JSON(http.StatusOK, value)
}
func (h g8Handler) submitCase(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	var input struct {
		SourceHash     string    `json:"source_candidate_hash"`
		Summary        string    `json:"summary"`
		Trigger        string    `json:"trigger"`
		Impact         string    `json:"impact"`
		Disposition    string    `json:"disposition"`
		Outcome        string    `json:"outcome"`
		Tags           []string  `json:"tags"`
		RetentionUntil time.Time `json:"retention_until"`
	}
	if decodeAndRestore(c, &input) != nil || strings.TrimSpace(input.SourceHash) == "" || strings.TrimSpace(input.Summary) == "" || strings.TrimSpace(input.Trigger) == "" || strings.TrimSpace(input.Impact) == "" || strings.TrimSpace(input.Disposition) == "" || strings.TrimSpace(input.Outcome) == "" {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "案例提交内容无效")
		return
	}
	h.mutate(c, actor, "submit_exception_case_candidate", c.Param("candidate_id"), http.StatusCreated, func(service services.G8Service) (any, error) {
		return service.SubmitCase(c, actor, c.Param("candidate_id"), map[string]any{"source_candidate_hash": input.SourceHash, "summary": input.Summary, "trigger": input.Trigger, "impact": input.Impact, "disposition": input.Disposition, "outcome": input.Outcome, "tags": input.Tags, "retention_until": input.RetentionUntil})
	})
}
func (h g8Handler) auditFilters(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	var input struct {
		Query string `json:"query"`
	}
	if c.ShouldBindJSON(&input) != nil || strings.TrimSpace(input.Query) == "" {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "审计查询无效")
		return
	}
	value, err := h.service.SuggestAuditFilters(c, actor, input.Query)
	if err != nil {
		writeG8Error(c, err)
		return
	}
	c.JSON(http.StatusOK, value)
}
func (h g8Handler) draftNotification(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	var input struct {
		NotificationID string `json:"notification_id"`
		Instruction    string `json:"instruction"`
	}
	if c.ShouldBindJSON(&input) != nil || strings.TrimSpace(input.NotificationID) == "" {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "通知草稿请求无效")
		return
	}
	value, err := h.service.DraftNotification(c, actor, input.NotificationID, input.Instruction)
	if err != nil {
		writeG8Error(c, err)
		return
	}
	c.JSON(http.StatusOK, value)
}
func (h g8Handler) sendDraft(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	var input struct {
		SourceHash string `json:"source_hash"`
		Body       string `json:"body"`
	}
	if decodeAndRestore(c, &input) != nil || strings.TrimSpace(input.SourceHash) == "" || strings.TrimSpace(input.Body) == "" {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "通知发送内容无效")
		return
	}
	h.mutate(c, actor, "send_notification_draft", c.Param("draft_id"), http.StatusAccepted, func(service services.G8Service) (any, error) {
		n, err := service.SendDraft(c, actor, c.Param("draft_id"), input.SourceHash, input.Body)
		return gin.H{"id": n.ID, "draft_id": c.Param("draft_id"), "status": "accepted", "accepted_at": n.CreatedAt}, err
	})
}

// decodeAndRestore keeps the byte-exact request body available to the shared
// idempotency middleware after a G8 write handler validates its JSON shape.
func decodeAndRestore(c *gin.Context, target any) error {
	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		return err
	}
	c.Request.Body = io.NopCloser(strings.NewReader(string(body)))
	return json.Unmarshal(body, target)
}

func (h g8Handler) mutate(c *gin.Context, actor entities.Actor, operation, aggregateID string, status int, work func(services.G8Service) (any, error)) {
	// G7's idempotency helper atomically stores the exact first response with
	// the G8 service transaction; its nested transaction is a PostgreSQL savepoint.
	g7Handler{db: h.db}.mutate(c, actor, operation, aggregateID, status, func(tx *gorm.DB) (any, error) { return work(h.service.WithDatabase(tx)) })
}

func writeG8Error(c *gin.Context, err error) {
	switch {
	case errors.Is(err, gorm.ErrRecordNotFound):
		writeProblem(c, http.StatusNotFound, "urn:problem:not-found", "未找到", "资源不存在或不属于当前中心")
	case errors.Is(err, services.ErrInvalidOpaqueReference):
		writeProblem(c, http.StatusConflict, "urn:problem:invalid-reference", "请求冲突", "候选或草稿引用已失效")
	default:
		writeProblem(c, http.StatusInternalServerError, "urn:problem:internal", "内部错误", "处理辅助请求失败")
	}
}

var _ = json.RawMessage{}
