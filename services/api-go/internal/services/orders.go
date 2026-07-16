package services

import (
	"context"
	"fmt"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"time"
)

type OrderService struct {
	db       *gorm.DB
	orders   repositories.OrderRepository
	projects repositories.ProjectRepository
}

func NewOrderService(db *gorm.DB) OrderService { return OrderService{db: db} }
func (s OrderService) Create(ctx context.Context, actor entities.Actor, input entities.OrderInput) (entities.OrderResult, error) {
	if err := validateInput(input); err != nil {
		return entities.OrderResult{}, err
	}
	var result entities.OrderResult
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		count, err := s.projects.Eligible(ctx, tx, actor.CenterID, input.CertificationType, input.ProjectIDs)
		if err != nil {
			return err
		}
		if count != int64(len(input.ProjectIDs)) {
			return fmt.Errorf("one or more projects are unavailable for this certification or center")
		}
		now := time.Now().UTC()
		order := models.Order{ID: uuid.NewString(), CenterID: actor.CenterID, SampleName: input.SampleName, SampleQuantity: input.SampleQuantity, CertificationType: input.CertificationType, Priority: input.Priority, PromisedFinishTime: input.PromisedFinishTime, Status: "pending_schedule", Version: 1, CreatedBy: actor.ID, UpdatedBy: actor.ID, CreatedAt: now, UpdatedAt: now}
		rows := make([]models.OrderProject, 0, len(input.ProjectIDs))
		for _, id := range input.ProjectIDs {
			rows = append(rows, models.OrderProject{ID: uuid.NewString(), OrderID: order.ID, ProjectID: id, Status: "pending", Version: 1})
		}
		if err = s.orders.Create(ctx, tx, order, rows); err != nil {
			return err
		}
		result = toResult(order, input.ProjectIDs)
		return nil
	})
	return result, err
}
func (s OrderService) Get(ctx context.Context, actor entities.Actor, id string) (entities.OrderResult, error) {
	item, err := s.orders.Find(ctx, s.db, actor.CenterID, id)
	if err != nil {
		return entities.OrderResult{}, err
	}
	rows, err := s.orders.Projects(ctx, s.db, id)
	if err != nil {
		return entities.OrderResult{}, err
	}
	ids := make([]string, 0, len(rows))
	for _, r := range rows {
		ids = append(ids, r.ProjectID)
	}
	return toResult(item, ids), nil
}
func (s OrderService) List(ctx context.Context, actor entities.Actor, page, pageSize int, query string) ([]entities.OrderResult, int64, error) {
	items, total, err := s.orders.List(ctx, s.db, actor.CenterID, page, pageSize, query)
	if err != nil {
		return nil, 0, err
	}
	results := make([]entities.OrderResult, 0, len(items))
	for _, item := range items {
		rows, err := s.orders.Projects(ctx, s.db, item.ID)
		if err != nil {
			return nil, 0, err
		}
		ids := make([]string, 0, len(rows))
		for _, row := range rows {
			ids = append(ids, row.ProjectID)
		}
		results = append(results, toResult(item, ids))
	}
	return results, total, nil
}

func (s OrderService) CreateRetest(ctx context.Context, actor entities.Actor, sourceID string, expected int64, projectIDs []string) (entities.OrderResult, error) {
	if len(projectIDs) == 0 {
		return entities.OrderResult{}, fmt.Errorf("at least one retest project is required")
	}
	var result entities.OrderResult
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		source, err := s.orders.Find(ctx, tx, actor.CenterID, sourceID)
		if err != nil {
			return err
		}
		if err := RequireVersion(expected, source.Version); err != nil {
			return err
		}
		rows, err := s.orders.Projects(ctx, tx, sourceID)
		if err != nil {
			return err
		}
		selected := make(map[string]struct{}, len(projectIDs))
		for _, id := range projectIDs {
			if _, duplicate := selected[id]; duplicate {
				return fmt.Errorf("duplicate retest project")
			}
			selected[id] = struct{}{}
		}
		sourceRows := make(map[string]models.OrderProject, len(rows))
		for _, row := range rows {
			sourceRows[row.ProjectID] = row
		}
		for _, id := range projectIDs {
			row, found := sourceRows[id]
			if !found || (row.Status != "retest_required" && row.Status != "failed") || row.RetestOrderID != nil {
				return fmt.Errorf("project %s is not eligible for retest", id)
			}
		}
		now := time.Now().UTC()
		child := models.Order{ID: uuid.NewString(), CenterID: actor.CenterID, SampleName: source.SampleName, SampleQuantity: source.SampleQuantity, CertificationType: source.CertificationType, Priority: source.Priority, PromisedFinishTime: source.PromisedFinishTime, Status: "pending_schedule", Version: 1, SourceOrderID: &source.ID, CreatedBy: actor.ID, UpdatedBy: actor.ID, CreatedAt: now, UpdatedAt: now}
		childRows := make([]models.OrderProject, 0, len(projectIDs))
		for _, id := range projectIDs {
			sourceRow := sourceRows[id]
			childRows = append(childRows, models.OrderProject{ID: uuid.NewString(), OrderID: child.ID, ProjectID: id, Status: "pending", SourceOrderProjectID: &sourceRow.ID, Version: 1})
			sourceRow.RetestOrderID = &child.ID
			if err := s.orders.UpdateProject(ctx, tx, sourceRow); err != nil {
				return err
			}
		}
		if err := s.orders.Create(ctx, tx, child, childRows); err != nil {
			return err
		}
		result = toResult(child, projectIDs)
		return nil
	})
	return result, err
}
func (s OrderService) ChangeStatus(ctx context.Context, actor entities.Actor, id string, expected int64, target, reason string) (entities.OrderResult, error) {
	var result entities.OrderResult
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		item, err := s.orders.Find(ctx, tx, actor.CenterID, id)
		if err != nil {
			return err
		}
		if err := RequireVersion(expected, item.Version); err != nil {
			return err
		}
		if !allowedTransition(item.Status, target) {
			return fmt.Errorf("invalid order transition %s to %s", item.Status, target)
		}
		if target == "paused" && reason == "" {
			return fmt.Errorf("pause reason is required")
		}
		if target == "paused" {
			running, err := s.orders.HasRunningProjects(ctx, tx, id)
			if err != nil {
				return err
			}
			if running {
				return fmt.Errorf("orders with running steps cannot be paused")
			}
		}
		item.Status = target
		item.PauseReason = nil
		if target == "paused" {
			item.PauseReason = &reason
		}
		item.Version++
		item.UpdatedBy = actor.ID
		item.UpdatedAt = time.Now().UTC()
		if err = s.orders.Update(ctx, tx, item); err != nil {
			return err
		}
		rows, err := s.orders.Projects(ctx, tx, id)
		if err != nil {
			return err
		}
		ids := make([]string, 0, len(rows))
		for _, row := range rows {
			ids = append(ids, row.ProjectID)
		}
		result = toResult(item, ids)
		return nil
	})
	return result, err
}
func (s OrderService) Update(ctx context.Context, actor entities.Actor, id string, expected int64, patch entities.OrderPatch) (entities.OrderResult, error) {
	var result entities.OrderResult
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		item, err := s.orders.Find(ctx, tx, actor.CenterID, id)
		if err != nil {
			return err
		}
		if err := RequireVersion(expected, item.Version); err != nil {
			return err
		}
		if item.Status != "pending_schedule" && item.Status != "scheduled" {
			return fmt.Errorf("order status does not permit updates")
		}
		if patch.SampleName == nil && patch.SampleQuantity == nil && patch.CertificationType == nil && patch.Priority == nil && patch.PromisedFinishTime == nil && patch.ProjectIDs == nil {
			return fmt.Errorf("order patch is empty")
		}
		if item.Status == "scheduled" && (patch.SampleName != nil || patch.SampleQuantity != nil || patch.CertificationType != nil || patch.ProjectIDs != nil) {
			return fmt.Errorf("scheduled orders only permit priority and promised finish updates")
		}
		if patch.Priority != nil {
			if !validPriority(*patch.Priority) {
				return fmt.Errorf("invalid priority")
			}
			item.Priority = *patch.Priority
		}
		if patch.PromisedFinishTime != nil {
			item.PromisedFinishTime = *patch.PromisedFinishTime
		}
		if item.Status == "pending_schedule" {
			if patch.SampleName != nil {
				if *patch.SampleName == "" {
					return fmt.Errorf("sample name is required")
				}
				item.SampleName = *patch.SampleName
			}
			if patch.SampleQuantity != nil {
				if *patch.SampleQuantity < 1 {
					return fmt.Errorf("sample quantity must be positive")
				}
				item.SampleQuantity = *patch.SampleQuantity
			}
			if patch.CertificationType != nil {
				if !validCertificationType(*patch.CertificationType) {
					return fmt.Errorf("invalid certification type")
				}
				item.CertificationType = *patch.CertificationType
			}
			if patch.CertificationType != nil || patch.ProjectIDs != nil {
				projectIDs, err := s.projectIDs(ctx, tx, id, patch.ProjectIDs)
				if err != nil {
					return err
				}
				count, err := s.projects.Eligible(ctx, tx, actor.CenterID, item.CertificationType, projectIDs)
				if err != nil {
					return err
				}
				if count != int64(len(projectIDs)) {
					return fmt.Errorf("one or more projects are unavailable for this certification or center")
				}
				if patch.ProjectIDs != nil {
					projects := make([]models.OrderProject, 0, len(projectIDs))
					for _, projectID := range projectIDs {
						projects = append(projects, models.OrderProject{ID: uuid.NewString(), OrderID: id, ProjectID: projectID, Status: "pending", Version: 1})
					}
					if err := s.orders.ReplaceProjects(ctx, tx, id, projects); err != nil {
						return err
					}
				}
			}
		}
		item.Version++
		item.UpdatedBy = actor.ID
		item.UpdatedAt = time.Now().UTC()
		if err := s.orders.Update(ctx, tx, item); err != nil {
			return err
		}
		rows, err := s.orders.Projects(ctx, tx, id)
		if err != nil {
			return err
		}
		ids := make([]string, 0, len(rows))
		for _, row := range rows {
			ids = append(ids, row.ProjectID)
		}
		result = toResult(item, ids)
		return nil
	})
	return result, err
}

func (s OrderService) projectIDs(ctx context.Context, db *gorm.DB, orderID string, replacement *[]string) ([]string, error) {
	if replacement != nil {
		if len(*replacement) == 0 {
			return nil, fmt.Errorf("at least one project is required")
		}
		return *replacement, nil
	}
	rows, err := s.orders.Projects(ctx, db, orderID)
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, row.ProjectID)
	}
	return ids, nil
}
func allowedTransition(from, target string) bool {
	return (target == "cancelled" && (from == "pending_schedule" || from == "scheduled" || from == "paused")) || (target == "paused" && (from == "pending_schedule" || from == "scheduled" || from == "in_progress")) || (target == "pending_schedule" && from == "paused")
}
func validateInput(in entities.OrderInput) error {
	if in.SampleName == "" || in.SampleQuantity < 1 || len(in.ProjectIDs) == 0 {
		return fmt.Errorf("order fields are incomplete")
	}
	if !validCertificationType(in.CertificationType) {
		return fmt.Errorf("invalid certification type")
	}
	return nil
}
func validCertificationType(value string) bool {
	return value == "CCC" || value == "CVC" || value == "international"
}
func validPriority(value string) bool {
	return value == "normal" || value == "urgent" || value == "vip"
}
func toResult(o models.Order, ids []string) entities.OrderResult {
	return entities.OrderResult{ID: o.ID, SampleName: o.SampleName, SampleQuantity: o.SampleQuantity, CertificationType: o.CertificationType, Priority: o.Priority, PromisedFinishTime: o.PromisedFinishTime, Status: o.Status, Version: o.Version, CreatedAt: o.CreatedAt, ProjectIDs: ids}
}
