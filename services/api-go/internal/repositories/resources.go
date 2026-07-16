package repositories

import (
	"context"
	"fmt"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type ResourceRepository struct{}

func (ResourceRepository) CurrentVersion(ctx context.Context, db *gorm.DB, entityType, centerID, sourceID string) (int64, bool, error) {
	var row struct{ SourceVersion int64 }
	table, err := resourceTable(entityType)
	if err != nil {
		return 0, false, err
	}
	err = db.WithContext(ctx).Table(table).Select("source_version").Where("center_id = ? AND source_id = ?", centerID, sourceID).Take(&row).Error
	if err == gorm.ErrRecordNotFound {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, fmt.Errorf("read resource version: %w", err)
	}
	return row.SourceVersion, true, nil
}

func (ResourceRepository) UpsertEquipment(ctx context.Context, tx *gorm.DB, item models.Equipment) error {
	return tx.WithContext(ctx).Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "center_id"}, {Name: "source_id"}}, DoUpdates: clause.AssignmentColumns([]string{"name", "status", "capacity", "active", "source_version", "updated_at"})}).Create(&item).Error
}
func (ResourceRepository) UpsertEmployee(ctx context.Context, tx *gorm.DB, item models.Employee) error {
	return tx.WithContext(ctx).Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "center_id"}, {Name: "source_id"}}, DoUpdates: clause.AssignmentColumns([]string{"name", "active", "source_version", "updated_at"})}).Create(&item).Error
}
func (ResourceRepository) UpsertShift(ctx context.Context, tx *gorm.DB, item models.Shift) error {
	return tx.WithContext(ctx).Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "center_id"}, {Name: "source_id"}}, DoUpdates: clause.AssignmentColumns([]string{"name", "start_time", "end_time", "active", "source_version"})}).Create(&item).Error
}
func (ResourceRepository) UpsertUnavailability(ctx context.Context, tx *gorm.DB, item models.Unavailability) error {
	return tx.WithContext(ctx).Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "center_id"}, {Name: "source_id"}}, DoUpdates: clause.AssignmentColumns([]string{"entity_id", "starts_at", "ends_at", "reason", "active", "source_version"})}).Create(&item).Error
}

func resourceTable(entityType string) (string, error) {
	switch entityType {
	case "equipment":
		return "equipment", nil
	case "employee":
		return "employees", nil
	case "shift":
		return "shifts", nil
	case "unavailability":
		return "unavailability", nil
	default:
		return "", fmt.Errorf("unsupported resource entity type %q", entityType)
	}
}
