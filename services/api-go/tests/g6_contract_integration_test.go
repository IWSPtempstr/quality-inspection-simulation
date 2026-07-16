package tests

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api"
	redisclient "github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/redis"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
	"gorm.io/datatypes"
	"gorm.io/gorm"
)

func TestG6ContractLifecycleAndWriteback(t *testing.T) {
	ctx, db := g6RepairDatabase(t)
	actor := entities.Actor{ID: "scheduler-contract", CenterID: "center-contract", Roles: []entities.Role{entities.RoleScheduler}}
	service := services.NewScheduleService(db, &g6RepairLocker{})

	preview := g6ContractReadyPreview(t, ctx, db, service, actor)
	t.Run("reject is terminal and center scoped", func(t *testing.T) {
		rejected, err := service.Reject(ctx, actor, preview.ID, preview.Version)
		if err != nil || rejected.Status != entities.PreviewRejected {
			t.Fatalf("reject = (%q, %v), want rejected", rejected.Status, err)
		}
		if _, err := service.Approve(ctx, actor, preview.ID, rejected.Version); err == nil {
			t.Fatal("approve rejected preview error = nil, want terminal transition rejection")
		}
		other := entities.Actor{ID: "scheduler-other", CenterID: "center-other", Roles: []entities.Role{entities.RoleScheduler}}
		if _, err := service.Get(ctx, other, preview.ID); err == nil {
			t.Fatal("other center loaded preview, want isolation")
		}
	})

	t.Run("concurrent approval has exactly one winner", func(t *testing.T) {
		p := g6ContractReadyPreview(t, ctx, db, service, actor)
		start := make(chan struct{})
		results := make(chan error, 2)
		var wg sync.WaitGroup
		for range 2 {
			wg.Add(1)
			go func() {
				defer wg.Done()
				<-start
				_, err := service.Approve(ctx, actor, p.ID, p.Version)
				results <- err
			}()
		}
		close(start)
		wg.Wait()
		close(results)
		successes := 0
		for err := range results {
			if err == nil {
				successes++
			}
		}
		if successes != 1 {
			t.Fatalf("concurrent approval successes = %d, want 1", successes)
		}
		var outbox int64
		if err := db.Model(&models.OutboxEvent{}).Where("aggregate_id = ? AND event_type = ?", p.ID, "schedule.writeback").Count(&outbox).Error; err != nil {
			t.Fatalf("count approval outbox: %v", err)
		}
		if outbox != 1 {
			t.Fatalf("approval outbox rows = %d, want 1", outbox)
		}
		// This subtest exercises approval contention only. Mark its writeback as
		// handled so later partner assertions observe only their own event.
		if err := db.Model(&models.OutboxEvent{}).Where("aggregate_id = ? AND event_type = ?", p.ID, "schedule.writeback").Update("published_at", time.Now().UTC()).Error; err != nil {
			t.Fatalf("isolate concurrent approval outbox: %v", err)
		}
	})

	t.Run("partner response controls formal version", func(t *testing.T) {
		for _, response := range []struct {
			name      string
			status    int
			wantState string
			wantCount int64
		}{
			{name: "success", status: http.StatusNoContent, wantState: entities.PreviewApproved, wantCount: 1},
			{name: "conflict", status: http.StatusConflict, wantState: entities.PreviewConflicted, wantCount: 0},
			{name: "precondition", status: http.StatusPreconditionFailed, wantState: entities.PreviewConflicted, wantCount: 0},
		} {
			t.Run(response.name, func(t *testing.T) {
				p := g6ContractReadyPreview(t, ctx, db, service, actor)
				snap, err := (repositories.ScheduleRepository{}).Snapshot(ctx, db, p.SnapshotID)
				if err != nil {
					t.Fatalf("load snapshot: %v", err)
				}
				approved, err := service.Approve(ctx, actor, p.ID, p.Version)
				if err != nil || approved.Status != entities.PreviewApprovedPendingWriteback {
					t.Fatalf("approve = (%q, %v)", approved.Status, err)
				}
				calls := 0
				partner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					calls++
					if r.Method != http.MethodPut || r.Header.Get("Idempotency-Key") == "" || r.Header.Get("If-Match") != fmt.Sprint(snap.BaseScheduleVersion) {
						t.Errorf("partner request = %s key=%q if-match=%q", r.Method, r.Header.Get("Idempotency-Key"), r.Header.Get("If-Match"))
					}
					if want := fmt.Sprintf("/internal/v1/centers/center-contract/schedule-versions/%d", snap.BaseScheduleVersion+1); r.URL.Path != want {
						t.Errorf("partner path = %q, want %q", r.URL.Path, want)
					}
					w.WriteHeader(response.status)
				}))
				defer partner.Close()
				worker := services.NewScheduleWritebackWorker(db, services.HTTPPartnerClient{BaseURL: partner.URL, Client: partner.Client()})
				if err := worker.PublishPending(ctx, 100); err != nil {
					t.Fatalf("publish writeback: %v", err)
				}
				if calls != 1 {
					t.Fatalf("partner calls = %d, want 1", calls)
				}
				stored, err := (repositories.ScheduleRepository{}).Preview(ctx, db, actor.CenterID, p.ID, false)
				if err != nil || stored.Status != response.wantState {
					t.Fatalf("stored preview = (%q, %v), want %q", stored.Status, err, response.wantState)
				}
				var versions int64
				if err := db.Model(&models.ScheduleVersion{}).Where("preview_id = ?", p.ID).Count(&versions).Error; err != nil {
					t.Fatalf("count formal versions: %v", err)
				}
				if versions != response.wantCount {
					t.Fatalf("formal versions = %d, want %d", versions, response.wantCount)
				}
			})
		}
	})

	t.Run("timeout leaves preview and outbox available for retry", func(t *testing.T) {
		p := g6ContractReadyPreview(t, ctx, db, service, actor)
		if _, err := service.Approve(ctx, actor, p.ID, p.Version); err != nil {
			t.Fatalf("approve: %v", err)
		}
		partner := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { time.Sleep(100 * time.Millisecond) }))
		defer partner.Close()
		worker := services.NewScheduleWritebackWorker(db, services.HTTPPartnerClient{BaseURL: partner.URL, Client: &http.Client{Timeout: 10 * time.Millisecond}})
		if err := worker.PublishPending(ctx, 100); err != nil {
			t.Fatalf("timeout writeback should release for retry: %v", err)
		}
		stored, err := (repositories.ScheduleRepository{}).Preview(ctx, db, actor.CenterID, p.ID, false)
		if err != nil || stored.Status != entities.PreviewApprovedPendingWriteback {
			t.Fatalf("timeout preview = (%q, %v), want pending writeback", stored.Status, err)
		}
		var outbox models.OutboxEvent
		if err := db.Where("aggregate_id = ? AND event_type = ?", p.ID, "schedule.writeback").First(&outbox).Error; err != nil {
			t.Fatalf("load writeback outbox: %v", err)
		}
		if outbox.ClaimedAt != nil || outbox.PublishedAt != nil {
			t.Fatalf("timed-out outbox claimed=%v published=%v, want released unpublished", outbox.ClaimedAt, outbox.PublishedAt)
		}
	})
}

func TestG6CallbackSnapshotMismatchAndRedisOutage(t *testing.T) {
	ctx, db := g6RepairDatabase(t)
	actor := entities.Actor{ID: "scheduler-contract", CenterID: "center-contract", Roles: []entities.Role{entities.RoleScheduler}}
	service := services.NewScheduleService(db, &g6RepairLocker{})
	p := g6ContractReadyPreview(t, ctx, db, service, actor)
	snap, err := (repositories.ScheduleRepository{}).Snapshot(ctx, db, p.SnapshotID)
	if err != nil {
		t.Fatalf("load snapshot: %v", err)
	}
	router := api.NewRouterWithScheduling(slog.New(slog.NewTextHandler(io.Discard, nil)), db, &g6RepairLocker{}, "fixture-token", g6RepairAuthenticator())
	for _, bad := range []map[string]any{
		{"snapshot_id": "wrong", "input_hash": snap.InputHash, "version": p.Version, "candidate": map[string]any{}, "normalized_steps": []any{}},
		{"snapshot_id": p.SnapshotID, "input_hash": "sha256:wrong", "version": p.Version, "candidate": map[string]any{}, "normalized_steps": []any{}},
		{"snapshot_id": p.SnapshotID, "input_hash": snap.InputHash, "version": p.Version + 1, "candidate": map[string]any{}, "normalized_steps": []any{}},
	} {
		body, marshalErr := json.Marshal(bad)
		if marshalErr != nil {
			t.Fatalf("marshal callback: %v", marshalErr)
		}
		req := httptest.NewRequest(http.MethodPost, "/internal/v1/schedule-previews/"+p.ID+"/candidate", bytes.NewReader(body))
		req.Header.Set("X-Internal-Service-Token", "fixture-token")
		res := httptest.NewRecorder()
		router.ServeHTTP(res, req)
		if res.Code != http.StatusConflict {
			t.Fatalf("mismatched callback = %d: %s, want 409", res.Code, res.Body.String())
		}
	}

	ready := g6ContractReadyPreview(t, ctx, db, service, actor)
	container, debouncer := g6ContractRedis(t, ctx)
	if err := container.Terminate(ctx); err != nil {
		t.Fatalf("stop Redis for outage: %v", err)
	}
	approvalRouter := api.NewRouterWithScheduling(slog.New(slog.NewTextHandler(io.Discard, nil)), db, debouncer, "fixture-token", api.AuthenticatorFunc(func(context.Context, string) (entities.Actor, error) { return actor, nil }))
	response := g6RepairRequest(t, approvalRouter, http.MethodPost, "/api/v1/schedule-previews/"+ready.ID+"/approve", "outage-key", fmt.Sprint(ready.Version), nil)
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("Redis outage approval = %d: %s, want 503", response.Code, response.Body.String())
	}
	stored, err := (repositories.ScheduleRepository{}).Preview(ctx, db, actor.CenterID, ready.ID, false)
	if err != nil || stored.Status != entities.PreviewPendingReview || stored.Version != ready.Version {
		t.Fatalf("Redis outage mutated preview = (%q, %d, %v)", stored.Status, stored.Version, err)
	}
	var formal int64
	if err := db.Model(&models.ScheduleVersion{}).Where("preview_id = ?", ready.ID).Count(&formal).Error; err != nil {
		t.Fatalf("count formal schedules: %v", err)
	}
	if formal != 0 {
		t.Fatalf("Redis outage formal schedules = %d, want 0", formal)
	}
}

func TestG6SnapshotPersistsFrozenStepEvidence(t *testing.T) {
	ctx, db := g6RepairDatabase(t)
	actor := entities.Actor{ID: "scheduler-contract", CenterID: "center-contract", Roles: []entities.Role{entities.RoleScheduler}}
	now := time.Now().UTC()
	steps, err := json.Marshal([]map[string]any{
		{"id": "running", "status": "running", "starts_at": now.Add(8 * time.Hour).Format(time.RFC3339Nano)},
		{"id": "near", "status": "planned", "starts_at": now.Add(90 * time.Minute).Format(time.RFC3339Nano)},
		{"id": "future", "status": "planned", "starts_at": now.Add(3 * time.Hour).Format(time.RFC3339Nano)},
	})
	if err != nil {
		t.Fatalf("marshal formal steps: %v", err)
	}
	preview := entities.SchedulePreview{ID: "00000000-0000-0000-0000-000000000001", CenterID: actor.CenterID, SnapshotID: "00000000-0000-0000-0000-000000000002", Status: entities.PreviewApproved, Version: 1, CreatedAt: now, UpdatedAt: now}
	if err := db.Create(&models.ScheduleSnapshot{ID: preview.SnapshotID, CenterID: actor.CenterID, InputHash: "seed", AsOf: now, Payload: datatypes.JSON(`{}`), CreatedAt: now}).Error; err != nil {
		t.Fatalf("seed snapshot: %v", err)
	}
	if err := db.Create(&models.SchedulePreview{ID: preview.ID, CenterID: preview.CenterID, SnapshotID: preview.SnapshotID, Status: preview.Status, Version: preview.Version, CreatedAt: now, UpdatedAt: now}).Error; err != nil {
		t.Fatalf("seed preview: %v", err)
	}
	if err := (repositories.ScheduleRepository{}).CreateVersion(ctx, db, entities.ScheduleVersion{ID: "4f67b488-5a82-47bf-865a-9141b1be4b29", CenterID: actor.CenterID, PreviewID: preview.ID, Version: 1, Steps: steps, CreatedAt: now}); err != nil {
		t.Fatalf("seed formal version: %v", err)
	}

	created, err := services.NewScheduleService(db, &g6RepairLocker{}).Create(ctx, actor)
	if err != nil {
		t.Fatalf("create snapshot with formal steps: %v", err)
	}
	snap, err := (repositories.ScheduleRepository{}).Snapshot(ctx, db, created.SnapshotID)
	if err != nil {
		t.Fatalf("load created snapshot: %v", err)
	}
	var payload struct {
		FrozenSteps []map[string]any `json:"frozen_steps"`
	}
	if err := json.Unmarshal(snap.Payload, &payload); err != nil {
		t.Fatalf("decode snapshot: %v", err)
	}
	if len(payload.FrozenSteps) != 2 {
		t.Fatalf("frozen steps = %#v, want running and near-term steps only", payload.FrozenSteps)
	}
}

func g6ContractReadyPreview(t *testing.T, ctx context.Context, db *gorm.DB, service services.ScheduleService, actor entities.Actor) entities.SchedulePreview {
	t.Helper()
	p, err := service.Create(ctx, actor)
	if err != nil {
		t.Fatalf("create preview: %v", err)
	}
	snap, err := (repositories.ScheduleRepository{}).Snapshot(ctx, db, p.SnapshotID)
	if err != nil {
		t.Fatalf("load snapshot: %v", err)
	}
	p, err = service.Candidate(ctx, p.ID, p.SnapshotID, snap.InputHash, p.Version, json.RawMessage(`{"score":1}`), json.RawMessage(`[]`))
	if err != nil {
		t.Fatalf("write candidate: %v", err)
	}
	return p
}

func g6ContractRedis(t *testing.T, ctx context.Context) (testcontainers.Container, *redisclient.Debouncer) {
	t.Helper()
	container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{ContainerRequest: testcontainers.ContainerRequest{Image: "redis:7-alpine", ExposedPorts: []string{"6379/tcp"}, WaitingFor: wait.ForListeningPort("6379/tcp").WithStartupTimeout(60 * time.Second)}, Started: true})
	if err != nil {
		t.Fatalf("start Redis: %v", err)
	}
	t.Cleanup(func() { _ = container.Terminate(ctx) })
	host, err := container.Host(ctx)
	if err != nil {
		t.Fatalf("get Redis host: %v", err)
	}
	port, err := container.MappedPort(ctx, "6379/tcp")
	if err != nil {
		t.Fatalf("get Redis port: %v", err)
	}
	debouncer, err := redisclient.Open(fmt.Sprintf("redis://%s:%s/0", host, port.Port()))
	if err != nil {
		t.Fatalf("open Redis: %v", err)
	}
	t.Cleanup(func() { _ = debouncer.Close() })
	return container, debouncer
}
