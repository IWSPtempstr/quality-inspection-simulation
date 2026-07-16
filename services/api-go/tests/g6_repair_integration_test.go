package tests

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

func TestG6PreviewReplayCandidateAuditAndOutboxClaimRelease(t *testing.T) {
	ctx, db := g6RepairDatabase(t)
	router := api.NewRouterWithScheduling(slog.New(slog.NewTextHandler(io.Discard, nil)), db, &g6RepairLocker{}, "fixture-token", g6RepairAuthenticator())

	first := g6RepairRequest(t, router, http.MethodPost, "/api/v1/schedule-previews", "preview-key", "", nil)
	if first.Code != http.StatusCreated {
		t.Fatalf("create preview = %d: %s", first.Code, first.Body.String())
	}
	replay := g6RepairRequest(t, router, http.MethodPost, "/api/v1/schedule-previews", "preview-key", "", nil)
	if replay.Code != first.Code || !bytes.Equal(replay.Body.Bytes(), first.Body.Bytes()) {
		t.Fatalf("preview replay = (%d, %s), want first response (%d, %s)", replay.Code, replay.Body.String(), first.Code, first.Body.String())
	}

	var response struct {
		ID         string `json:"id"`
		SnapshotID string `json:"snapshot_id"`
		Version    int64  `json:"version"`
	}
	if err := json.Unmarshal(first.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode preview: %v", err)
	}
	snapshot, err := (repositories.ScheduleRepository{}).Snapshot(ctx, db, response.SnapshotID)
	if err != nil {
		t.Fatalf("load snapshot: %v", err)
	}
	candidate := map[string]any{"snapshot_id": response.SnapshotID, "input_hash": snapshot.InputHash, "version": response.Version, "candidate": map[string]any{"score": 1}, "normalized_steps": []any{}}
	body, err := json.Marshal(candidate)
	if err != nil {
		t.Fatalf("marshal candidate: %v", err)
	}
	request := httptest.NewRequest(http.MethodPost, "/internal/v1/schedule-previews/"+response.ID+"/candidate", bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Internal-Service-Token", "fixture-token")
	callback := httptest.NewRecorder()
	router.ServeHTTP(callback, request)
	if callback.Code != http.StatusOK {
		t.Fatalf("candidate callback = %d: %s", callback.Code, callback.Body.String())
	}
	var audits int64
	if err := db.Model(&models.AuditLog{}).Where("entity_id = ? AND action = ?", response.ID, "schedule_preview_candidate_received").Count(&audits).Error; err != nil {
		t.Fatalf("count candidate audits: %v", err)
	}
	if audits != 1 {
		t.Fatalf("candidate audits = %d, want 1", audits)
	}

	now := time.Now().UTC()
	foreign := models.OutboxEvent{ID: uuid.NewString(), EventType: "schedule.rebuild.requested", AggregateType: "resource", AggregateID: "resource-1", Payload: []byte(`{"center_id":"center-g6"}`), OccurredAt: now, CreatedAt: now}
	if err := db.Create(&foreign).Error; err != nil {
		t.Fatalf("create G5 outbox event: %v", err)
	}
	worker := services.NewScheduleWritebackWorker(db, g6RepairPartner{})
	if err := worker.PublishPending(ctx, 10); err != nil {
		t.Fatalf("writeback worker: %v", err)
	}
	var stored models.OutboxEvent
	if err := db.First(&stored, "id = ?", foreign.ID).Error; err != nil {
		t.Fatalf("load G5 outbox event: %v", err)
	}
	if stored.ClaimedAt != nil || stored.PublishedAt != nil {
		t.Fatalf("G5 outbox after G6 worker = claimed %v published %v, want released unpublished", stored.ClaimedAt, stored.PublishedAt)
	}
}

func g6RepairDatabase(t *testing.T) (context.Context, *gorm.DB) {
	t.Helper()
	ctx := context.Background()
	container, url := startPostgres(t, ctx)
	t.Cleanup(func() { _ = container.Terminate(ctx) })
	db, err := postgres.Open(ctx, url)
	if err != nil {
		t.Fatalf("open PostgreSQL: %v", err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatalf("get PostgreSQL DB: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })
	if err := postgres.Migrate(ctx, sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("migrate PostgreSQL: %v", err)
	}
	return ctx, db
}

func g6RepairAuthenticator() api.Authenticator {
	return api.AuthenticatorFunc(func(context.Context, string) (entities.Actor, error) {
		return entities.Actor{ID: "scheduler-g6", CenterID: "center-g6", Roles: []entities.Role{entities.RoleScheduler}}, nil
	})
}

func g6RepairRequest(t *testing.T, router http.Handler, method, path, key, version string, body []byte) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, path, bytes.NewReader(body))
	request.Header.Set("Idempotency-Key", key)
	if version != "" {
		request.Header.Set("If-Match", version)
	}
	request.AddCookie(&http.Cookie{Name: api.SessionCookieName, Value: "verified-session"})
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	return response
}

type g6RepairLocker struct{ mu sync.Mutex }

func (l *g6RepairLocker) AcquireApprovalLock(context.Context, string, time.Duration) (bool, error) {
	l.mu.Lock()
	return true, nil
}
func (l *g6RepairLocker) ReleaseApprovalLock(context.Context, string) error {
	l.mu.Unlock()
	return nil
}

type g6RepairPartner struct{}

func (g6RepairPartner) PutSchedule(context.Context, string, int64, []byte, string, int64) (int, string, error) {
	return http.StatusNoContent, "", nil
}
