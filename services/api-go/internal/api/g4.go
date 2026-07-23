package api

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api/generated"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

func mountG4Routes(api *gin.RouterGroup, authenticator Authenticator, db *gorm.DB) {
	auth := ActorMiddleware(authenticator)
	ordersRead := RequireCapability(entities.CapabilityOrdersRead)
	ordersWrite := RequireCapability(entities.CapabilityOrdersWrite)
	resourcesRead := RequireCapability(entities.CapabilityResourcesRead)
	h := g4Handler{db: db, orders: services.NewOrderService(db)}

	api.GET("/projects", auth, ordersRead, h.listProjects)
	api.GET("/orders", auth, ordersRead, h.listOrders)
	api.GET("/orders/:order_id", auth, ordersRead, h.getOrder)
	api.POST("/orders", auth, ordersWrite, RequireIdempotencyKey(), h.createOrder)
	api.PATCH("/orders/:order_id", auth, ordersWrite, RequireIdempotencyKey(), RequireVersion(), h.updateOrder)
	api.DELETE("/orders/:order_id", auth, ordersWrite, RequireIdempotencyKey(), RequireVersion(), h.cancelOrder)
	api.POST("/orders/:order_id/retests", auth, ordersWrite, RequireIdempotencyKey(), RequireVersion(), h.createRetest)
	api.POST("/orders/:order_id/pause", auth, ordersWrite, RequireIdempotencyKey(), RequireVersion(), h.pauseOrder)
	api.POST("/orders/:order_id/resume", auth, ordersWrite, RequireIdempotencyKey(), RequireVersion(), h.resumeOrder)
	api.GET("/resources/equipment", auth, resourcesRead, h.listEquipment)
	api.GET("/resources/employees", auth, resourcesRead, h.listEmployees)
	api.GET("/resources/shifts", auth, resourcesRead, h.listShifts)
	api.GET("/resources/unavailability", auth, resourcesRead, h.listUnavailability)
}

type g4Handler struct {
	db     *gorm.DB
	orders services.OrderService
}

func (h g4Handler) listProjects(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	projects, err := (repositories.ProjectRepository{}).List(c.Request.Context(), h.db, actor.CenterID)
	if err != nil {
		writeG4Error(c, err)
		return
	}
	result := make([]generated.DetectionProject, 0, len(projects))
	for _, project := range projects {
		var types []models.ProjectCertificationType
		if err := h.db.Where("project_id = ?", project.ID).Find(&types).Error; err != nil {
			writeG4Error(c, err)
			return
		}
		certifications := make([]generated.CertificationType, 0, len(types))
		for _, typ := range types {
			certifications = append(certifications, generated.CertificationType(typ.CertificationType))
		}
		result = append(result, generated.DetectionProject{Id: project.ID, Code: project.Code, Name: project.Name, Active: project.Active, CertificationTypes: certifications})
	}
	c.JSON(http.StatusOK, result)
}

func (h g4Handler) listOrders(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	page, pageSize := pageParams(c)
	items, total, err := h.orders.List(c.Request.Context(), actor, page, pageSize, c.Query("q"))
	if err != nil {
		writeG4Error(c, err)
		return
	}
	result := make([]generated.Order, 0, len(items))
	for _, item := range items {
		result = append(result, generatedOrder(item))
	}
	c.JSON(http.StatusOK, generated.OrderPage{Items: result, Page: int32(page), PageSize: int32(pageSize), Total: int32(total)})
}

func (h g4Handler) getOrder(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	item, err := h.orders.Get(c.Request.Context(), actor, c.Param("order_id"))
	if err != nil {
		writeG4Error(c, err)
		return
	}
	c.JSON(http.StatusOK, generatedOrder(item))
}

func (h g4Handler) createOrder(c *gin.Context) {
	var input generated.OrderInput
	body, ok := decodeG4(c, &input)
	if !ok {
		return
	}
	actor, _ := ActorFromContext(c)
	h.mutate(c, "create_order", "orders", body, http.StatusCreated, func(tx *gorm.DB) (any, error) {
		return services.NewOrderService(tx).Create(c.Request.Context(), actor, entities.OrderInput{SampleName: input.SampleName, SampleQuantity: int(input.SampleQuantity), CertificationType: string(input.CertificationType), Priority: input.Priority, PromisedFinishTime: input.PromisedFinishTime, ProjectIDs: input.ProjectIds})
	})
}

func (h g4Handler) createRetest(c *gin.Context) {
	var input generated.CreateRetestRequest
	body, ok := decodeG4(c, &input)
	if !ok {
		return
	}
	if strings.TrimSpace(input.Reason) == "" {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "复测原因不能为空")
		return
	}
	actor, _ := ActorFromContext(c)
	expected, _ := ExpectedVersion(c)
	id := c.Param("order_id")
	h.mutate(c, "create_retest", id, body, http.StatusCreated, func(tx *gorm.DB) (any, error) {
		return services.NewOrderService(tx).CreateRetest(c.Request.Context(), actor, id, expected, input.ProjectIds)
	})
}

func (h g4Handler) updateOrder(c *gin.Context) {
	var input entities.OrderPatch
	body, ok := decodeG4(c, &input)
	if !ok {
		return
	}
	actor, _ := ActorFromContext(c)
	expected, _ := ExpectedVersion(c)
	id := c.Param("order_id")
	h.mutate(c, "update_order", id, body, http.StatusOK, func(tx *gorm.DB) (any, error) {
		return services.NewOrderService(tx).Update(c.Request.Context(), actor, id, expected, input)
	})
}

func (h g4Handler) cancelOrder(c *gin.Context) {
	body := []byte("{}")
	actor, _ := ActorFromContext(c)
	expected, _ := ExpectedVersion(c)
	id := c.Param("order_id")
	h.mutate(c, "cancel_order", id, body, http.StatusNoContent, func(tx *gorm.DB) (any, error) {
		_, err := services.NewOrderService(tx).ChangeStatus(c.Request.Context(), actor, id, expected, "cancelled", "")
		return nil, err
	})
}

func (h g4Handler) pauseOrder(c *gin.Context) {
	var input generated.PauseOrderRequest
	body, ok := decodeG4(c, &input)
	if !ok {
		return
	}
	actor, _ := ActorFromContext(c)
	expected, _ := ExpectedVersion(c)
	id := c.Param("order_id")
	h.mutate(c, "pause_order", id, body, http.StatusOK, func(tx *gorm.DB) (any, error) {
		return services.NewOrderService(tx).ChangeStatus(c.Request.Context(), actor, id, expected, "paused", input.Reason)
	})
}

func (h g4Handler) resumeOrder(c *gin.Context) {
	body, ok := decodeG4(c, &struct{}{})
	if !ok {
		return
	}
	actor, _ := ActorFromContext(c)
	expected, _ := ExpectedVersion(c)
	id := c.Param("order_id")
	h.mutate(c, "resume_order", id, body, http.StatusOK, func(tx *gorm.DB) (any, error) {
		return services.NewOrderService(tx).ChangeStatus(c.Request.Context(), actor, id, expected, "pending_schedule", "")
	})
}

func (h g4Handler) mutate(c *gin.Context, operation, aggregateID string, body []byte, success int, work func(*gorm.DB) (any, error)) {
	actor, _ := ActorFromContext(c)
	key := c.GetHeader("Idempotency-Key")
	scope := strings.Join([]string{actor.CenterID, actor.ID, operation, aggregateID}, ":")
	repository := repositories.IdempotencyRepository{}
	if record, found, err := repository.Find(c.Request.Context(), h.db, scope, key); err != nil {
		writeG4Error(c, err)
		return
	} else if found {
		if record.RequestHash != g4RequestHash(body) {
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
	if err := h.db.Transaction(func(tx *gorm.DB) error {
		if err := (services.IdempotencyService{}).Register(c.Request.Context(), tx, scope, key, body); err != nil {
			return err
		}
		value, err := work(tx)
		if err != nil {
			return err
		}
		response, err = json.Marshal(generatedOrderValue(value))
		if err != nil {
			return err
		}
		record, found, err := repository.Find(c.Request.Context(), tx, scope, key)
		if err != nil || !found {
			return fmt.Errorf("find claimed idempotency record: %w", err)
		}
		return repository.Complete(c.Request.Context(), tx, record.ID, success, contentType, response)
	}); err != nil {
		if errors.Is(err, entities.ErrIdempotencyReplay) {
			writeProblem(c, http.StatusConflict, "urn:problem:idempotency-in-progress", "请求冲突", "相同请求正在处理")
			return
		}
		writeG4Error(c, err)
		return
	}
	c.Data(success, contentType, response)
}

func (h g4Handler) listEquipment(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	var items []models.Equipment
	if err := h.db.Where("center_id = ? AND active", actor.CenterID).Find(&items).Error; err != nil {
		writeG4Error(c, err)
		return
	}
	out := make([]generated.Equipment, 0, len(items))
	for _, item := range items {
		var ids []string
		if err := h.db.Table("equipment_projects").Where("equipment_id = ?", item.ID).Pluck("project_id", &ids).Error; err != nil {
			writeG4Error(c, err)
			return
		}
		out = append(out, generated.Equipment{Id: item.ID, Name: item.Name, Status: item.Status, Capacity: int32(item.Capacity), ProjectIds: ids, Version: int32(item.SourceVersion)})
	}
	c.JSON(http.StatusOK, out)
}
func (h g4Handler) listEmployees(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	var items []models.Employee
	if err := h.db.Where("center_id = ? AND active", actor.CenterID).Find(&items).Error; err != nil {
		writeG4Error(c, err)
		return
	}
	out := make([]generated.Employee, 0, len(items))
	for _, item := range items {
		var skills []string
		if err := h.db.Table("employee_skills").Where("employee_id = ?", item.ID).Pluck("project_id", &skills).Error; err != nil {
			writeG4Error(c, err)
			return
		}
		out = append(out, generated.Employee{Id: item.ID, Name: item.Name, Skills: skills, Version: int32(item.SourceVersion)})
	}
	c.JSON(http.StatusOK, out)
}
func (h g4Handler) listShifts(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	// PostgreSQL TIME is returned by pgx as a string. Scanning it into
	// time.Time is driver-dependent and failed in the live stack, so this
	// read model deliberately retains the database representation.
	var items []struct {
		ID        string
		Name      string
		StartTime string
		EndTime   string
	}
	if err := h.db.Table("shifts").Select("id, name, start_time::text AS start_time, end_time::text AS end_time").Where("center_id = ? AND active", actor.CenterID).Scan(&items).Error; err != nil {
		writeG4Error(c, err)
		return
	}
	out := make([]generated.Shift, 0, len(items))
	for _, item := range items {
		out = append(out, generated.Shift{Id: item.ID, Name: item.Name, StartTime: item.StartTime, EndTime: item.EndTime})
	}
	c.JSON(http.StatusOK, out)
}
func (h g4Handler) listUnavailability(c *gin.Context) {
	actor, _ := ActorFromContext(c)
	var items []models.Unavailability
	if err := h.db.Where("center_id = ? AND active", actor.CenterID).Find(&items).Error; err != nil {
		writeG4Error(c, err)
		return
	}
	out := make([]generated.Unavailability, 0, len(items))
	for _, item := range items {
		out = append(out, generated.Unavailability{Id: item.ID, EntityId: item.EntityID, StartsAt: item.StartsAt, EndsAt: item.EndsAt, Reason: item.Reason})
	}
	c.JSON(http.StatusOK, out)
}

func decodeG4(c *gin.Context, target any) ([]byte, bool) {
	body, err := io.ReadAll(c.Request.Body)
	if err != nil || json.Unmarshal(body, target) != nil {
		writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", "请求体必须是有效 JSON")
		return nil, false
	}
	return body, true
}
func generatedOrderValue(value any) any {
	if result, ok := value.(entities.OrderResult); ok {
		return generatedOrder(result)
	}
	return value
}
func generatedOrder(value entities.OrderResult) generated.Order {
	return generated.Order{Id: value.ID, SampleName: value.SampleName, SampleQuantity: int32(value.SampleQuantity), CertificationType: generated.CertificationType(value.CertificationType), Priority: value.Priority, PromisedFinishTime: value.PromisedFinishTime, ProjectIds: value.ProjectIDs, Status: generated.OrderStatus(value.Status), Version: int32(value.Version), CreatedAt: value.CreatedAt}
}
func pageParams(c *gin.Context) (int, int) {
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	size, _ := strconv.Atoi(c.DefaultQuery("page_size", "25"))
	if page < 1 {
		page = 1
	}
	if size < 1 || size > 200 {
		size = 25
	}
	return page, size
}
func g4RequestHash(body []byte) string {
	sum := sha256.Sum256(body)
	return "sha256:" + hex.EncodeToString(sum[:])
}
func valueOrJSON(value *string) string {
	if value == nil || *value == "" {
		return "application/json; charset=utf-8"
	}
	return *value
}
func writeG4Error(c *gin.Context, err error) {
	if errors.Is(err, gorm.ErrRecordNotFound) {
		writeProblem(c, http.StatusNotFound, "urn:problem:not-found", "未找到", "请求的资源不存在")
		return
	}
	if errors.Is(err, entities.ErrVersionConflict) || strings.Contains(err.Error(), "invalid order transition") || strings.Contains(err.Error(), "not eligible") || strings.Contains(err.Error(), "cannot be paused") {
		writeProblem(c, http.StatusConflict, "urn:problem:conflict", "请求冲突", err.Error())
		return
	}
	writeProblem(c, http.StatusBadRequest, "urn:problem:invalid-request", "请求无效", err.Error())
}

var _ = time.Time{}
