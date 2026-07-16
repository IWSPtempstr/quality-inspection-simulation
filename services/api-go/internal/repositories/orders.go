package repositories

import (
	"context"
	"fmt"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"gorm.io/gorm"
)

type OrderRepository struct{}

func (OrderRepository) Find(ctx context.Context, db *gorm.DB, centerID, id string) (models.Order, error) {
	var item models.Order
	err := db.WithContext(ctx).Where("id = ? AND center_id = ?", id, centerID).First(&item).Error
	if err != nil {
		return item, fmt.Errorf("find order: %w", err)
	}
	return item, nil
}
func (OrderRepository) Create(ctx context.Context, tx *gorm.DB, item models.Order, projects []models.OrderProject) error {
	if err := tx.WithContext(ctx).Create(&item).Error; err != nil {
		return err
	}
	return tx.WithContext(ctx).Create(&projects).Error
}
func (OrderRepository) Projects(ctx context.Context, db *gorm.DB, orderID string) ([]models.OrderProject, error) {
	var items []models.OrderProject
	err := db.WithContext(ctx).Where("order_id = ?", orderID).Find(&items).Error
	return items, err
}
func (OrderRepository) Update(ctx context.Context, tx *gorm.DB, item models.Order) error {
	return tx.WithContext(ctx).Save(&item).Error
}

func (OrderRepository) UpdateProject(ctx context.Context, tx *gorm.DB, item models.OrderProject) error {
	return tx.WithContext(ctx).Save(&item).Error
}

func (OrderRepository) ReplaceProjects(ctx context.Context, tx *gorm.DB, orderID string, projects []models.OrderProject) error {
	if err := tx.WithContext(ctx).Where("order_id = ?", orderID).Delete(&models.OrderProject{}).Error; err != nil {
		return err
	}
	return tx.WithContext(ctx).Create(&projects).Error
}

func (OrderRepository) List(ctx context.Context, db *gorm.DB, centerID string, page, pageSize int, query string) ([]models.Order, int64, error) {
	base := db.WithContext(ctx).Model(&models.Order{}).Where("center_id = ?", centerID)
	if query != "" {
		base = base.Where("sample_name ILIKE ?", "%"+query+"%")
	}
	var total int64
	if err := base.Count(&total).Error; err != nil {
		return nil, 0, err
	}
	var items []models.Order
	err := base.Order("created_at DESC, id").Offset((page - 1) * pageSize).Limit(pageSize).Find(&items).Error
	return items, total, err
}

func (OrderRepository) HasRunningProjects(ctx context.Context, db *gorm.DB, orderID string) (bool, error) {
	var count int64
	err := db.WithContext(ctx).Model(&models.OrderProject{}).Where("order_id = ? AND status = ?", orderID, "running").Count(&count).Error
	return count > 0, err
}
