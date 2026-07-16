package repositories

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"gorm.io/datatypes"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type ScheduleRepository struct{}

func (ScheduleRepository) CreateSnapshot(ctx context.Context, tx *gorm.DB, v entities.ScheduleSnapshot) error {
	return tx.WithContext(ctx).Create(&models.ScheduleSnapshot{ID: v.ID, CenterID: v.CenterID, InputHash: v.InputHash, AsOf: v.AsOf, BaseScheduleVersion: v.BaseScheduleVersion, ResourceSnapshotVersion: v.ResourceSnapshotVersion, Payload: datatypes.JSON(v.Payload), CreatedAt: v.CreatedAt}).Error
}
func (ScheduleRepository) CreatePreview(ctx context.Context, tx *gorm.DB, v entities.SchedulePreview) error {
	return tx.WithContext(ctx).Create(&models.SchedulePreview{ID: v.ID, CenterID: v.CenterID, SnapshotID: v.SnapshotID, Status: v.Status, Version: v.Version, CreatedAt: v.CreatedAt, UpdatedAt: v.UpdatedAt}).Error
}
func (ScheduleRepository) Preview(ctx context.Context, db *gorm.DB, centerID, id string, lock bool) (entities.SchedulePreview, error) {
	q := db.WithContext(ctx)
	if lock {
		q = q.Clauses(clause.Locking{Strength: "UPDATE"})
	}
	var v models.SchedulePreview
	if centerID != "" {
		q = q.Where("center_id = ?", centerID)
	}
	err := q.Where("id = ?", id).First(&v).Error
	if err != nil {
		return entities.SchedulePreview{}, fmt.Errorf("find preview: %w", err)
	}
	return previewEntity(v), nil
}
func (ScheduleRepository) Snapshot(ctx context.Context, db *gorm.DB, id string) (entities.ScheduleSnapshot, error) {
	var v models.ScheduleSnapshot
	if err := db.WithContext(ctx).First(&v, "id = ?", id).Error; err != nil {
		return entities.ScheduleSnapshot{}, err
	}
	return entities.ScheduleSnapshot{ID: v.ID, CenterID: v.CenterID, InputHash: v.InputHash, AsOf: v.AsOf, BaseScheduleVersion: v.BaseScheduleVersion, ResourceSnapshotVersion: v.ResourceSnapshotVersion, Payload: json.RawMessage(v.Payload), CreatedAt: v.CreatedAt}, nil
}
func (ScheduleRepository) UpdatePreview(ctx context.Context, tx *gorm.DB, v entities.SchedulePreview, expected int64) error {
	r := tx.WithContext(ctx).Model(&models.SchedulePreview{}).Where("id = ? AND center_id = ? AND version = ?", v.ID, v.CenterID, expected).Updates(map[string]any{"status": v.Status, "candidate": datatypes.JSON(v.Candidate), "normalized_steps": datatypes.JSON(v.NormalizedSteps), "version": v.Version, "partner_failure": v.PartnerFailure, "updated_at": v.UpdatedAt})
	if r.Error != nil {
		return r.Error
	}
	if r.RowsAffected != 1 {
		return entities.ErrVersionConflict
	}
	return nil
}
func (ScheduleRepository) CreateVersion(ctx context.Context, tx *gorm.DB, v entities.ScheduleVersion) error {
	return tx.WithContext(ctx).Create(&models.ScheduleVersion{ID: v.ID, CenterID: v.CenterID, Version: v.Version, PreviewID: v.PreviewID, Steps: datatypes.JSON(v.Steps), CreatedAt: v.CreatedAt}).Error
}
func (ScheduleRepository) NextVersion(ctx context.Context, tx *gorm.DB, centerID string) (int64, error) {
	var n int64
	err := tx.WithContext(ctx).Raw("SELECT COALESCE(MAX(version),0)+1 FROM schedule_versions WHERE center_id = ? FOR UPDATE", centerID).Scan(&n).Error
	return n, err
}
func (ScheduleRepository) IsMissing(err error) bool { return errors.Is(err, gorm.ErrRecordNotFound) }
func previewEntity(v models.SchedulePreview) entities.SchedulePreview {
	return entities.SchedulePreview{ID: v.ID, CenterID: v.CenterID, SnapshotID: v.SnapshotID, Status: v.Status, Candidate: json.RawMessage(v.Candidate), NormalizedSteps: json.RawMessage(v.NormalizedSteps), Version: v.Version, PartnerFailure: v.PartnerFailure, CreatedAt: v.CreatedAt, UpdatedAt: v.UpdatedAt}
}
