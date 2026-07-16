package services

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"strings"
	"time"
)

var ErrApprovalLockUnavailable = errors.New("approval lock unavailable")
var ErrInvalidPreviewTransition = errors.New("invalid preview transition")

type ApprovalLocker interface {
	AcquireApprovalLock(context.Context, string, time.Duration) (bool, error)
	ReleaseApprovalLock(context.Context, string) error
}
type ScheduleService struct {
	db     *gorm.DB
	repo   repositories.ScheduleRepository
	outbox repositories.OutboxRepository
	audit  AuditService
	locks  ApprovalLocker
}

func NewScheduleService(db *gorm.DB, locks ApprovalLocker) ScheduleService {
	return ScheduleService{db: db, locks: locks}
}

func (s ScheduleService) Locks() ApprovalLocker { return s.locks }
func (s ScheduleService) Get(ctx context.Context, actor entities.Actor, id string) (entities.SchedulePreview, error) {
	return s.repo.Preview(ctx, s.db, actor.CenterID, id, false)
}
func (s ScheduleService) Create(ctx context.Context, actor entities.Actor) (entities.SchedulePreview, error) {
	now := time.Now().UTC()
	payload, base, resource, err := s.snapshotPayload(ctx, actor.CenterID, now)
	if err != nil {
		return entities.SchedulePreview{}, err
	}
	sum := sha256.Sum256(payload)
	hash := "sha256:" + hex.EncodeToString(sum[:])
	snapshot := entities.ScheduleSnapshot{ID: uuid.NewString(), CenterID: actor.CenterID, InputHash: hash, AsOf: now, BaseScheduleVersion: base, ResourceSnapshotVersion: resource, Payload: payload, CreatedAt: now}
	preview := entities.SchedulePreview{ID: uuid.NewString(), CenterID: actor.CenterID, SnapshotID: snapshot.ID, Status: entities.PreviewPendingCandidate, Version: 1, CreatedAt: now, UpdatedAt: now}
	err = s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := s.repo.CreateSnapshot(ctx, tx, snapshot); err != nil {
			return err
		}
		if err := s.repo.CreatePreview(ctx, tx, preview); err != nil {
			return err
		}
		return s.audit.Append(ctx, tx, AuditEntry{Actor: actor, Action: "schedule_preview_created", EntityType: "schedule_preview", EntityID: preview.ID, Outcome: "success", Detail: []byte("{}")})
	})
	return preview, err
}
func (s ScheduleService) Candidate(ctx context.Context, previewID, snapshotID, inputHash string, version int64, candidate, steps json.RawMessage) (entities.SchedulePreview, error) {
	if !json.Valid(candidate) || !json.Valid(steps) {
		return entities.SchedulePreview{}, fmt.Errorf("invalid candidate JSON")
	}
	var result entities.SchedulePreview
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		p, e := s.repo.Preview(ctx, tx, "", previewID, true)
		if e != nil {
			return e
		}
		snap, e := s.repo.Snapshot(ctx, tx, p.SnapshotID)
		if e != nil {
			return e
		}
		if p.Status != entities.PreviewPendingCandidate || p.Version != version || p.SnapshotID != snapshotID || snap.InputHash != inputHash {
			return ErrInvalidPreviewTransition
		}
		p.Status = entities.PreviewPendingReview
		p.Candidate = append([]byte(nil), candidate...)
		p.NormalizedSteps = append([]byte(nil), steps...)
		p.Version++
		p.UpdatedAt = time.Now().UTC()
		if e = s.repo.UpdatePreview(ctx, tx, p, version); e != nil {
			return e
		}
		if e = s.audit.Append(ctx, tx, AuditEntry{Actor: entities.Actor{ID: "internal-scheduler", CenterID: p.CenterID}, Action: "schedule_preview_candidate_received", EntityType: "schedule_preview", EntityID: p.ID, BeforeVersion: &version, AfterVersion: &p.Version, Outcome: "success", Detail: []byte("{}")}); e != nil {
			return e
		}
		result = p
		return nil
	})
	return result, err
}
func (s ScheduleService) Reject(ctx context.Context, actor entities.Actor, id string, expected int64) (entities.SchedulePreview, error) {
	return s.transition(ctx, actor, id, expected, entities.PreviewRejected)
}
func (s ScheduleService) Approve(ctx context.Context, actor entities.Actor, id string, expected int64) (entities.SchedulePreview, error) {
	if s.locks == nil {
		return entities.SchedulePreview{}, ErrApprovalLockUnavailable
	}
	locked, err := s.locks.AcquireApprovalLock(ctx, id, 15*time.Second)
	if err != nil {
		return entities.SchedulePreview{}, ErrApprovalLockUnavailable
	}
	if !locked {
		return entities.SchedulePreview{}, entities.ErrVersionConflict
	}
	preview, transitionErr := s.transition(ctx, actor, id, expected, entities.PreviewApprovedPendingWriteback)
	releaseErr := s.locks.ReleaseApprovalLock(ctx, id)
	if transitionErr != nil {
		return preview, transitionErr
	}
	if releaseErr != nil {
		return preview, fmt.Errorf("release approval lock: %w", releaseErr)
	}
	return preview, nil
}
func (s ScheduleService) transition(ctx context.Context, actor entities.Actor, id string, expected int64, to string) (entities.SchedulePreview, error) {
	var result entities.SchedulePreview
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		p, e := s.repo.Preview(ctx, tx, actor.CenterID, id, true)
		if e != nil {
			return e
		}
		if p.Version != expected {
			return entities.ErrVersionConflict
		}
		allowed := (to == entities.PreviewRejected && p.Status == entities.PreviewPendingReview) || (to == entities.PreviewApprovedPendingWriteback && p.Status == entities.PreviewPendingReview)
		if !allowed {
			return ErrInvalidPreviewTransition
		}
		before := p.Version
		p.Status = to
		p.Version++
		p.UpdatedAt = time.Now().UTC()
		if e = s.repo.UpdatePreview(ctx, tx, p, before); e != nil {
			return e
		}
		if to == entities.PreviewApprovedPendingWriteback {
			payload, _ := json.Marshal(map[string]any{"preview_id": p.ID, "center_id": p.CenterID})
			if e = s.outbox.Enqueue(ctx, tx, entities.OutboxEvent{ID: uuid.NewString(), EventType: "schedule.writeback", AggregateType: "schedule_preview", AggregateID: p.ID, Payload: payload, OccurredAt: p.UpdatedAt, CreatedAt: p.UpdatedAt}); e != nil {
				return e
			}
		}
		if e = s.audit.Append(ctx, tx, AuditEntry{Actor: actor, Action: "schedule_preview_" + to, EntityType: "schedule_preview", EntityID: id, BeforeVersion: &before, AfterVersion: &p.Version, Outcome: "success", Detail: []byte("{}")}); e != nil {
			return e
		}
		result = p
		return nil
	})
	return result, err
}
func (s ScheduleService) snapshotPayload(ctx context.Context, center string, asOf time.Time) ([]byte, int64, int64, error) {
	var orders, resources, versions []map[string]any
	if err := s.db.WithContext(ctx).Table("orders").Where("center_id = ?", center).Order("id").Find(&orders).Error; err != nil {
		return nil, 0, 0, err
	}
	if err := s.db.WithContext(ctx).Table("schedule_versions").Where("center_id = ?", center).Order("version").Find(&versions).Error; err != nil {
		return nil, 0, 0, err
	}
	for _, table := range []string{"equipment", "employees", "shifts", "unavailability"} {
		var rows []map[string]any
		if err := s.db.WithContext(ctx).Table(table).Where("center_id = ?", center).Order("id").Find(&rows).Error; err != nil {
			return nil, 0, 0, err
		}
		resources = append(resources, rows...)
	}
	var base, resource int64
	for _, v := range versions {
		if n, ok := v["version"].(int64); ok && n > base {
			base = n
		}
	}
	for _, r := range resources {
		if n, ok := r["source_version"].(int64); ok && n > resource {
			resource = n
		}
	}
	frozen, err := frozenSteps(versions, asOf.Add(120*time.Minute))
	if err != nil {
		return nil, 0, 0, err
	}
	// Formal version JSON stays immutable; G7 runtime execution rows are the
	// authoritative source for steps that have started since approval.
	var running []map[string]any
	if err := s.db.WithContext(ctx).Table("schedule_steps").Where("center_id = ? AND status = ?", center, "running").Order("id").Find(&running).Error; err == nil {
		frozen = append(frozen, running...)
	} else if !strings.Contains(err.Error(), "does not exist") {
		return nil, 0, 0, err
	}
	payload, err := json.Marshal(map[string]any{"as_of": asOf.Format(time.RFC3339Nano), "orders": orders, "resources": resources, "formal_schedule": versions, "frozen_steps": frozen, "freeze_before": asOf.Add(120 * time.Minute).Format(time.RFC3339Nano)})
	return payload, base, resource, err
}

func frozenSteps(versions []map[string]any, freezeBefore time.Time) ([]map[string]any, error) {
	frozen := make([]map[string]any, 0)
	for _, version := range versions {
		rawSteps, ok := version["steps"]
		if !ok || rawSteps == nil {
			continue
		}
		data, err := scheduleStepsJSON(rawSteps)
		if err != nil {
			return nil, fmt.Errorf("marshal formal schedule steps: %w", err)
		}
		var steps []map[string]any
		if err := json.Unmarshal(data, &steps); err != nil {
			return nil, fmt.Errorf("decode formal schedule steps: %w", err)
		}
		for _, step := range steps {
			if step["status"] == "running" {
				frozen = append(frozen, step)
				continue
			}
			startsAt, ok := step["starts_at"].(string)
			if !ok {
				continue
			}
			start, err := time.Parse(time.RFC3339Nano, startsAt)
			if err == nil && !start.After(freezeBefore) {
				frozen = append(frozen, step)
			}
		}
	}
	return frozen, nil
}

func scheduleStepsJSON(value any) ([]byte, error) {
	switch steps := value.(type) {
	case []byte:
		return steps, nil
	case string:
		return []byte(steps), nil
	case json.RawMessage:
		return steps, nil
	default:
		return json.Marshal(steps)
	}
}
