package tests

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

const (
	idempotencyTestCenter = "center-idempotency"
	idempotencyTestActor  = "scheduler-idempotency"
)

func TestG4MutationReplaysPersistedFirstResponse(t *testing.T) {
	ctx, db := g4IdempotencyDatabase(t)
	seedG4EligibleProject(t, db, "00000000-0000-0000-0000-000000000101")
	router := g4IdempotencyRouter(db)

	body := []byte(`{"sample_name":"replay sample","sample_quantity":1,"certification_type":"CCC","priority":"urgent","promised_finish_time":"2026-07-20T08:00:00Z","project_ids":["00000000-0000-0000-0000-000000000101"]}`)
	first := g4OrderRequest(t, router, "replay-key", body)
	if first.Code != http.StatusCreated {
		t.Fatalf("first status = %d, want %d; body = %s", first.Code, http.StatusCreated, first.Body.String())
	}
	firstContentType := first.Header().Get("Content-Type")
	firstBody := append([]byte(nil), first.Body.Bytes()...)

	replay := g4OrderRequest(t, router, "replay-key", body)
	if replay.Code != first.Code {
		t.Fatalf("replay status = %d, want stored status %d", replay.Code, first.Code)
	}
	if contentType := replay.Header().Get("Content-Type"); contentType != firstContentType {
		t.Fatalf("replay content type = %q, want stored content type %q", contentType, firstContentType)
	}
	if !bytes.Equal(replay.Body.Bytes(), firstBody) {
		t.Fatalf("replay JSON body = %s, want stored first body %s", replay.Body.String(), firstBody)
	}

	var orders int64
	if err := db.WithContext(ctx).Model(&models.Order{}).Where("center_id = ?", idempotencyTestCenter).Count(&orders).Error; err != nil {
		t.Fatalf("count orders: %v", err)
	}
	if orders != 1 {
		t.Fatalf("order executions = %d, want 1", orders)
	}
}

func TestG4FailedMutationDoesNotPersistIdempotencyClaim(t *testing.T) {
	ctx, db := g4IdempotencyDatabase(t)
	router := g4IdempotencyRouter(db)
	projectID := "00000000-0000-0000-0000-000000000102"
	body := []byte(`{"sample_name":"retry sample","sample_quantity":1,"certification_type":"CCC","priority":"normal","promised_finish_time":"2026-07-20T08:00:00Z","project_ids":["00000000-0000-0000-0000-000000000102"]}`)

	failed := g4OrderRequest(t, router, "retry-after-failure-key", body)
	if failed.Code != http.StatusBadRequest {
		t.Fatalf("failed mutation status = %d, want %d; body = %s", failed.Code, http.StatusBadRequest, failed.Body.String())
	}
	var claims int64
	if err := db.WithContext(ctx).Model(&models.IdempotencyRecord{}).Where("scope = ? AND idempotency_key = ?", idempotencyScope(), "retry-after-failure-key").Count(&claims).Error; err != nil {
		t.Fatalf("count idempotency claims: %v", err)
	}
	if claims != 0 {
		t.Fatalf("idempotency claims after failed mutation = %d, want 0", claims)
	}

	seedG4EligibleProject(t, db, projectID)
	retry := g4OrderRequest(t, router, "retry-after-failure-key", body)
	if retry.Code != http.StatusCreated {
		t.Fatalf("retry status = %d, want %d; body = %s", retry.Code, http.StatusCreated, retry.Body.String())
	}
}

func g4IdempotencyDatabase(t *testing.T) (context.Context, *gorm.DB) {
	t.Helper()
	ctx := context.Background()
	container, databaseURL := startPostgres(t, ctx)
	t.Cleanup(func() { _ = container.Terminate(ctx) })
	db, err := postgres.Open(ctx, databaseURL)
	if err != nil {
		t.Fatalf("open container database: %v", err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatalf("get SQL database: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })
	if err := postgres.Migrate(ctx, sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run Goose migrations: %v", err)
	}
	return ctx, db
}

func g4IdempotencyRouter(db *gorm.DB) *gin.Engine {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	return api.NewRouterWithDatabase(logger, db, api.AuthenticatorFunc(func(context.Context, string) (entities.Actor, error) {
		return entities.Actor{ID: idempotencyTestActor, CenterID: idempotencyTestCenter, Roles: []entities.Role{entities.RoleScheduler}}, nil
	}))
}

func g4OrderRequest(t *testing.T, router http.Handler, key string, body []byte) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(http.MethodPost, "/api/v1/orders", bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Idempotency-Key", key)
	request.AddCookie(&http.Cookie{Name: api.SessionCookieName, Value: "verified-session"})
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	return response
}

func seedG4EligibleProject(t *testing.T, db *gorm.DB, projectID string) {
	t.Helper()
	project := models.DetectionProject{ID: projectID, SourceID: "source-" + projectID, Code: "code-" + projectID, Name: "Replay project", Active: true, SourceVersion: 1}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("create detection project: %v", err)
	}
	if err := db.Create(&models.ProjectCertificationType{ProjectID: projectID, CertificationType: "CCC"}).Error; err != nil {
		t.Fatalf("create project certification type: %v", err)
	}
	if err := db.Create(&models.CenterProject{CenterID: idempotencyTestCenter, ProjectID: projectID, Active: true, SourceVersion: 1}).Error; err != nil {
		t.Fatalf("create center project: %v", err)
	}
}

func idempotencyScope() string {
	return idempotencyTestCenter + ":" + idempotencyTestActor + ":create_order:orders"
}
