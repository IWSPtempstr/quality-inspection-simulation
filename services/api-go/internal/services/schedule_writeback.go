package services

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"io"
	"net/http"
	"strings"
	"time"
)

type PartnerScheduleClient interface {
	PutSchedule(context.Context, string, int64, []byte, string, int64) (int, string, error)
}
type ScheduleWritebackWorker struct {
	db     *gorm.DB
	repo   repositories.ScheduleRepository
	outbox repositories.OutboxRepository
	client PartnerScheduleClient
}

func NewScheduleWritebackWorker(db *gorm.DB, client PartnerScheduleClient) ScheduleWritebackWorker {
	return ScheduleWritebackWorker{db: db, client: client}
}
func (w ScheduleWritebackWorker) PublishPending(ctx context.Context, limit int) error {
	var events []entities.OutboxEvent
	err := w.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var claimErr error
		events, claimErr = w.outbox.ClaimUnpublished(ctx, tx, limit)
		return claimErr
	})
	if err != nil {
		return err
	}
	count := 0
	for _, e := range events {
		if e.EventType != "schedule.writeback" {
			if err := w.outbox.ReleaseClaim(ctx, w.db, e.ID); err != nil {
				return err
			}
			continue
		}
		if count >= limit {
			break
		}
		count++
		if err := w.process(ctx, e); err != nil {
			return err
		}
	}
	return nil
}
func (w ScheduleWritebackWorker) process(ctx context.Context, event entities.OutboxEvent) error {
	var ref struct {
		PreviewID string `json:"preview_id"`
		CenterID  string `json:"center_id"`
	}
	if err := json.Unmarshal(event.Payload, &ref); err != nil {
		return err
	}
	p, err := w.repo.Preview(ctx, w.db, ref.CenterID, ref.PreviewID, false)
	if err != nil {
		return err
	}
	if p.Status != entities.PreviewApprovedPendingWriteback {
		return w.outbox.MarkPublished(ctx, w.db, event.ID)
	}
	snap, err := w.repo.Snapshot(ctx, w.db, p.SnapshotID)
	if err != nil {
		return err
	}
	var payload []byte
	payload, _ = json.Marshal(map[string]any{"center_id": p.CenterID, "preview_id": p.ID, "target_version": snap.BaseScheduleVersion + 1, "steps": json.RawMessage(p.NormalizedSteps)})
	status, body, callErr := w.client.PutSchedule(ctx, p.CenterID, snap.BaseScheduleVersion+1, payload, event.ID, snap.BaseScheduleVersion)
	if callErr != nil || status >= 500 {
		return w.outbox.ReleaseClaim(ctx, w.db, event.ID)
	}
	return w.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if status == 409 || status == 412 {
			failure := sanitize(body)
			p.Status = entities.PreviewConflicted
			p.PartnerFailure = &failure
			p.Version++
			p.UpdatedAt = time.Now().UTC()
			if err := w.repo.UpdatePreview(ctx, tx, p, p.Version-1); err != nil {
				return err
			}
			return w.outbox.MarkPublished(ctx, tx, event.ID)
		}
		if status < 200 || status >= 300 {
			failure := sanitize(body)
			p.Status = entities.PreviewFailed
			p.PartnerFailure = &failure
			p.Version++
			p.UpdatedAt = time.Now().UTC()
			if err := w.repo.UpdatePreview(ctx, tx, p, p.Version-1); err != nil {
				return err
			}
			return w.outbox.MarkPublished(ctx, tx, event.ID)
		}
		p.Status = entities.PreviewApproved
		p.Version++
		p.UpdatedAt = time.Now().UTC()
		if err := w.repo.UpdatePreview(ctx, tx, p, p.Version-1); err != nil {
			return err
		}
		if err := w.repo.CreateVersion(ctx, tx, entities.ScheduleVersion{ID: uuid.NewString(), CenterID: p.CenterID, PreviewID: p.ID, Version: snap.BaseScheduleVersion + 1, Steps: p.NormalizedSteps, CreatedAt: p.UpdatedAt}); err != nil {
			return err
		}
		steps, err := expandFormalSteps(p.CenterID, snap.BaseScheduleVersion+1, p.NormalizedSteps)
		if err != nil {
			return err
		}
		if err := (repositories.ExecutionRepository{}).CreateSteps(ctx, tx, steps); err != nil {
			return err
		}
		return w.outbox.MarkPublished(ctx, tx, event.ID)
	})
}

// expandFormalSteps copies the approved immutable version into independently-versioned
// execution rows. It never mutates the JSON retained on the formal version.
func expandFormalSteps(center string, version int64, raw json.RawMessage) ([]entities.ScheduleStep, error) {
	var inputs []struct {
		ID               string          `json:"id"`
		OrderID          string          `json:"order_id"`
		ProjectID        string          `json:"project_id"`
		EquipmentID      *string         `json:"equipment_id"`
		EmployeeIDs      json.RawMessage `json:"employee_ids"`
		StartsAt, EndsAt time.Time       `json:"-"`
		StartsAtText     string          `json:"starts_at"`
		EndsAtText       string          `json:"ends_at"`
	}
	if err := json.Unmarshal(raw, &inputs); err != nil {
		return nil, fmt.Errorf("decode normalized schedule steps: %w", err)
	}
	steps := make([]entities.ScheduleStep, 0, len(inputs))
	for _, in := range inputs {
		if in.ID == "" || in.OrderID == "" || in.ProjectID == "" {
			return nil, fmt.Errorf("normalized schedule step is missing identity")
		}
		starts, err := time.Parse(time.RFC3339, in.StartsAtText)
		if err != nil {
			return nil, fmt.Errorf("decode schedule step start: %w", err)
		}
		ends, err := time.Parse(time.RFC3339, in.EndsAtText)
		if err != nil {
			return nil, fmt.Errorf("decode schedule step end: %w", err)
		}
		ids := in.EmployeeIDs
		if len(ids) == 0 {
			ids = []byte("[]")
		}
		steps = append(steps, entities.ScheduleStep{ID: in.ID, CenterID: center, ScheduleVersion: version, OrderID: in.OrderID, ProjectID: in.ProjectID, EquipmentID: in.EquipmentID, EmployeeIDs: ids, StartsAt: starts, EndsAt: ends, Status: "scheduled", Version: 1})
	}
	return steps, nil
}
func sanitize(body string) string {
	body = strings.ReplaceAll(body, "\n", " ")
	if len(body) > 512 {
		body = body[:512]
	}
	return body
}

type HTTPPartnerClient struct {
	BaseURL    string
	Credential string
	Client     *http.Client
}

func (c HTTPPartnerClient) PutSchedule(ctx context.Context, center string, target int64, payload []byte, key string, base int64) (int, string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, strings.TrimRight(c.BaseURL, "/")+fmt.Sprintf("/internal/v1/centers/%s/schedule-versions/%d", center, target), bytes.NewReader(payload))
	if err != nil {
		return 0, "", err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", key)
	req.Header.Set("If-Match", fmt.Sprintf("%d", base))
	if credential := strings.TrimSpace(c.Credential); credential != "" {
		req.Header.Set("Authorization", "Bearer "+credential)
	}
	client := c.Client
	if client == nil {
		client = http.DefaultClient
	}
	res, err := client.Do(req)
	if err != nil {
		return 0, "", err
	}
	body, readErr := io.ReadAll(res.Body)
	closeErr := res.Body.Close()
	if readErr != nil {
		return 0, "", readErr
	}
	if closeErr != nil {
		return 0, "", closeErr
	}
	return res.StatusCode, string(body), nil
}
