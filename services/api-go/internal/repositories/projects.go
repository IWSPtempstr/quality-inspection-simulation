package repositories

import (
	"context"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"gorm.io/gorm"
)

type ProjectRepository struct{}

func (ProjectRepository) Eligible(ctx context.Context, db *gorm.DB, centerID, certification string, ids []string) (int64, error) {
	var count int64
	err := db.WithContext(ctx).Table("detection_projects p").Joins("JOIN center_projects cp ON cp.project_id = p.id").Joins("JOIN project_certification_types pct ON pct.project_id = p.id").Where("cp.center_id = ? AND cp.active AND p.active AND pct.certification_type = ? AND p.id IN ?", centerID, certification, ids).Count(&count).Error
	return count, err
}
func (ProjectRepository) List(ctx context.Context, db *gorm.DB, centerID string) ([]models.DetectionProject, error) {
	var rows []models.DetectionProject
	err := db.WithContext(ctx).Table("detection_projects p").Joins("JOIN center_projects cp ON cp.project_id = p.id").Where("cp.center_id = ? AND cp.active AND p.active", centerID).Find(&rows).Error
	return rows, err
}
