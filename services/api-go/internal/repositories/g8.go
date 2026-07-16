package repositories

import (
	"context"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"gorm.io/datatypes"
	"gorm.io/gorm"
)

type G8Repository struct{}

func (G8Repository) CreateCaseReview(ctx context.Context, tx *gorm.DB, review entities.ExceptionCaseReview) error {
	return tx.WithContext(ctx).Create(&models.ExceptionCaseReview{ID: review.ID, CenterID: review.CenterID, EventID: review.EventID, SubmittedBy: review.SubmittedBy, SourceCandidateHash: review.SourceCandidateHash, Submission: datatypes.JSON(review.Submission), RetentionUntil: review.RetentionUntil, Status: review.Status, Version: review.Version, SubmittedAt: review.SubmittedAt, CreatedAt: review.SubmittedAt}).Error
}

func (G8Repository) Notification(ctx context.Context, db *gorm.DB, centerID, id string) (entities.Notification, error) {
	var value models.Notification
	if err := db.WithContext(ctx).Where("center_id = ? AND id = ?", centerID, id).First(&value).Error; err != nil {
		return entities.Notification{}, err
	}
	return entities.Notification{ID: value.ID, CenterID: value.CenterID, RecipientID: value.RecipientID, OrderID: value.OrderID, Title: value.Title, Body: value.Body, Channel: value.Channel, Status: value.Status, Version: value.Version, CreatedAt: value.CreatedAt}, nil
}

func (G8Repository) CreateNotification(ctx context.Context, tx *gorm.DB, value entities.Notification) error {
	return tx.WithContext(ctx).Create(&models.Notification{ID: value.ID, CenterID: value.CenterID, RecipientID: value.RecipientID, OrderID: value.OrderID, Title: value.Title, Body: value.Body, Channel: value.Channel, Status: value.Status, Version: value.Version, CreatedAt: value.CreatedAt, UpdatedAt: value.CreatedAt}).Error
}

func (G8Repository) CreateDelivery(ctx context.Context, tx *gorm.DB, id, notificationID, channel string, now time.Time) error {
	return tx.WithContext(ctx).Create(&models.NotificationDelivery{ID: id, NotificationID: notificationID, Channel: channel, Status: "pending", CreatedAt: now, UpdatedAt: now}).Error
}
