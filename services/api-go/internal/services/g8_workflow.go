package services

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/repositories"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

type G8Service struct {
	db         *gorm.DB
	assistance AssistanceClient
	signer     OpaqueReferenceSigner
	repository repositories.G8Repository
	events     repositories.ExecutionRepository
	schedules  repositories.ScheduleRepository
	outbox     repositories.OutboxRepository
	audit      AuditService
}

func NewG8Service(db *gorm.DB, assistance AssistanceClient, signer OpaqueReferenceSigner) G8Service {
	return G8Service{db: db, assistance: assistance, signer: signer}
}

func (s G8Service) WithDatabase(db *gorm.DB) G8Service { s.db = db; return s }

func (s G8Service) Event(ctx context.Context, actor entities.Actor, id string) (entities.SystemEvent, error) {
	return s.events.Event(ctx, s.db, actor.CenterID, id, false)
}

func (s G8Service) Preflight(ctx context.Context, actor entities.Actor, scope, orderID, previewID string, resourceIDs []string) (map[string]any, error) {
	findings := make([]map[string]any, 0)
	switch scope {
	case "order":
		if strings.TrimSpace(orderID) == "" {
			findings = append(findings, finding("order_required", "order_id", "必须选择订单"))
		} else {
			var order models.Order
			if err := s.db.WithContext(ctx).Where("id=? AND center_id=?", orderID, actor.CenterID).First(&order).Error; err != nil {
				if errors.Is(err, gorm.ErrRecordNotFound) {
					findings = append(findings, finding("order_not_found", "order_id", "订单不存在或不属于当前中心"))
				} else {
					return nil, err
				}
			} else if order.PromisedFinishTime.IsZero() || !order.PromisedFinishTime.After(time.Now().UTC()) {
				findings = append(findings, finding("invalid_promised_finish_time", "promised_finish_time", "承诺完成时间必须在未来"))
			}
		}
	case "resource":
		for _, id := range resourceIDs {
			var count int64
			if err := s.db.WithContext(ctx).Table("equipment").Where("id=? AND center_id=? AND active=true", id, actor.CenterID).Count(&count).Error; err != nil {
				return nil, err
			}
			if count == 0 {
				findings = append(findings, finding("resource_unavailable", "resource_ids", "资源不存在、未启用或不属于当前中心"))
			}
		}
	case "schedule_preview":
		if strings.TrimSpace(previewID) == "" {
			findings = append(findings, finding("preview_required", "preview_id", "必须选择排程预览"))
		} else if _, err := s.schedules.Preview(ctx, s.db, actor.CenterID, previewID, false); err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				findings = append(findings, finding("preview_not_found", "preview_id", "预览不存在或不属于当前中心"))
			} else {
				return nil, err
			}
		}
	default:
		return nil, fmt.Errorf("invalid preflight scope")
	}
	result := map[string]any{"scope": scope, "status": map[bool]string{true: "blocked", false: "passed"}[len(findings) > 0], "findings": findings, "deterministic": true, "explanation_available": s.assistance != nil && len(findings) > 0, "degraded": s.assistance == nil}
	if s.assistance != nil && len(findings) > 0 {
		raw, err := s.assistance.ExplainDataQuality(ctx, mustJSON(map[string]any{"center_id": actor.CenterID, "actor_id": actor.ID, "correlation_id": correlationID(ctx), "scope": scope, "findings": findings}))
		if err != nil {
			result["degraded"] = true
		} else {
			mergeFindingSuggestions(findings, raw)
		}
	}
	return result, nil
}

func finding(code, field, message string) map[string]any {
	return map[string]any{"code": code, "severity": "error", "message": message, "field": field, "blocking": true}
}

func mergeFindingSuggestions(findings []map[string]any, raw json.RawMessage) {
	var result struct {
		Explanations []struct {
			Code, Explanation   string
			SuggestedCorrection *string `json:"suggested_correction"`
		} `json:"explanations"`
	}
	if json.Unmarshal(raw, &result) != nil {
		return
	}
	for _, explanation := range result.Explanations {
		for _, finding := range findings {
			if finding["code"] == explanation.Code && explanation.SuggestedCorrection != nil {
				finding["suggestion"] = *explanation.SuggestedCorrection
			}
		}
	}
}

func (s G8Service) Diagnose(ctx context.Context, actor entities.Actor, eventID string) (map[string]any, error) {
	event, err := s.Event(ctx, actor, eventID)
	if err != nil {
		return nil, err
	}
	result := map[string]any{"event_id": event.ID, "affected_order_ids": []string{}, "frozen_step_ids": []string{}, "sla_risks": []any{}, "affected_resources": []any{}, "evidence": []any{}, "resolved_case_ids": []string{}, "recommendations": []string{}, "evidence_gaps": []string{"assistance unavailable"}, "confidence": "insufficient", "tool_calls": []string{}, "degraded": true, "memory_summary_status": "degraded"}
	if s.assistance == nil {
		return result, nil
	}
	raw, err := s.assistance.Diagnose(ctx, mustJSON(map[string]any{"center_id": actor.CenterID, "actor_id": actor.ID, "correlation_id": correlationID(ctx), "event_id": event.ID, "schedule_version": 0, "resource_snapshot_version": 0}))
	if err != nil {
		return result, nil
	}
	var ai map[string]any
	if json.Unmarshal(raw, &ai) == nil {
		for key, value := range ai {
			result[key] = value
		}
		result["event_id"] = event.ID
	}
	return result, nil
}

func (s G8Service) Explain(ctx context.Context, actor entities.Actor, previewID, subjectType, subjectID string) (map[string]any, error) {
	preview, err := s.schedules.Preview(ctx, s.db, actor.CenterID, previewID, false)
	if err != nil {
		return nil, err
	}
	result := map[string]any{"preview_id": preview.ID, "subject_type": subjectType, "subject_id": subjectID, "summary": "无可用解释。", "constraint_reasons": []string{}, "tradeoffs": []string{}, "frozen_step_ids": []string{}, "blockers": []any{}, "fallback_reason": nil, "evidence_available": false, "degraded": true}
	if s.assistance == nil {
		return result, nil
	}
	raw, err := s.assistance.ExplainSchedule(ctx, mustJSON(map[string]any{"center_id": actor.CenterID, "actor_id": actor.ID, "correlation_id": correlationID(ctx), "preview_id": preview.ID, "subject_type": subjectType, "subject_id": subjectID, "persisted_result": json.RawMessage(preview.Candidate)}))
	if err != nil {
		return result, nil
	}
	var ai map[string]any
	if json.Unmarshal(raw, &ai) == nil {
		for key, value := range ai {
			result[key] = value
		}
		result["preview_id"], result["subject_type"], result["subject_id"] = preview.ID, subjectType, subjectID
	}
	return result, nil
}

func (s G8Service) SuggestAuditFilters(ctx context.Context, actor entities.Actor, query string) (map[string]any, error) {
	result := map[string]any{"original_query": query, "filters": []AuditFilter{}, "explanation": "无可用建议。", "uncertainty": true, "degraded": true}
	if s.assistance == nil {
		return result, nil
	}
	raw, err := s.assistance.SuggestAuditFilters(ctx, mustJSON(map[string]any{"center_id": actor.CenterID, "actor_id": actor.ID, "correlation_id": correlationID(ctx), "query": query, "allowed_fields": []string{"actor_id", "action", "entity_id", "created_at"}}))
	if err != nil {
		return result, nil
	}
	var ai struct {
		Filters     []AuditFilter `json:"filters"`
		Explanation string        `json:"explanation"`
		Uncertainty bool          `json:"uncertainty"`
		Degraded    bool          `json:"degraded"`
	}
	if json.Unmarshal(raw, &ai) != nil || ValidateAuditFilters(ai.Filters) != nil {
		return result, nil
	}
	return map[string]any{"original_query": query, "filters": ai.Filters, "explanation": ai.Explanation, "uncertainty": ai.Uncertainty, "degraded": ai.Degraded}, nil
}

func (s G8Service) Candidate(ctx context.Context, actor entities.Actor, eventID string) (map[string]any, error) {
	event, err := s.Event(ctx, actor, eventID)
	if err != nil {
		return nil, err
	}
	if event.Status != "closed" {
		return nil, ErrInvalidOpaqueReference
	}
	sourceHash := SourceHash(event.ID, event.CenterID, event.Status, string(event.Payload), value(event.Disposition))
	ref, err := s.signer.Sign("case", actor.CenterID, event.ID, sourceHash)
	if err != nil {
		return nil, err
	}
	result := map[string]any{"candidate_id": ref, "event_id": event.ID, "source_candidate_hash": sourceHash, "summary": "", "trigger": "", "impact": "", "disposition": value(event.Disposition), "outcome": "", "tags": []string{}, "evidence": []any{}, "retention_until": time.Now().UTC().AddDate(1, 0, 0), "status": "candidate"}
	if s.assistance == nil {
		return result, nil
	}
	payload := mustJSON(map[string]any{"center_id": actor.CenterID, "actor_id": actor.ID, "correlation_id": correlationID(ctx), "event_id": event.ID, "closed_event_snapshot": event})
	raw, err := s.assistance.CreateCaseCandidate(ctx, payload)
	if err != nil {
		return result, nil
	}
	var ai map[string]any
	if json.Unmarshal(raw, &ai) == nil {
		for _, key := range []string{"summary", "trigger", "impact", "disposition", "outcome", "tags", "evidence", "retention_until"} {
			if value, ok := ai[key]; ok {
				result[key] = value
			}
		}
	}
	return result, nil
}

func (s G8Service) SubmitCase(ctx context.Context, actor entities.Actor, candidateID string, input map[string]any) (entities.ExceptionCaseReview, error) {
	eventID, err := opaqueSubject(candidateID)
	hash, _ := input["source_candidate_hash"].(string)
	if err != nil || eventID == "" || hash == "" {
		return entities.ExceptionCaseReview{}, ErrInvalidOpaqueReference
	}
	if _, err := s.signer.Verify(candidateID, "case", actor.CenterID, eventID, hash); err != nil {
		return entities.ExceptionCaseReview{}, err
	}
	event, err := s.events.Event(ctx, s.db, actor.CenterID, eventID, false)
	if err != nil || event.Status != "closed" {
		if err != nil {
			return entities.ExceptionCaseReview{}, err
		}
		return entities.ExceptionCaseReview{}, ErrInvalidOpaqueReference
	}
	retention, ok := input["retention_until"].(time.Time)
	if !ok || !retention.After(time.Now().UTC()) {
		return entities.ExceptionCaseReview{}, fmt.Errorf("invalid retention")
	}
	now := time.Now().UTC()
	review := entities.ExceptionCaseReview{ID: uuid.NewString(), CenterID: actor.CenterID, EventID: eventID, SubmittedBy: actor.ID, SourceCandidateHash: hash, Submission: mustJSON(input), RetentionUntil: retention, Status: "pending_review", Version: 1, SubmittedAt: now}
	err = s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := s.repository.CreateCaseReview(ctx, tx, review); err != nil {
			return err
		}
		if err := s.outbox.Enqueue(ctx, tx, entities.OutboxEvent{ID: uuid.NewString(), EventType: "exception_case.review_submitted", AggregateType: "exception_case_review", AggregateID: review.ID, Payload: mustJSON(map[string]any{"center_id": review.CenterID, "case_review_id": review.ID}), OccurredAt: now, CreatedAt: now}); err != nil {
			return err
		}
		return s.audit.Append(ctx, tx, AuditEntry{Actor: actor, Action: "exception_case_review_submitted", EntityType: "exception_case_review", EntityID: review.ID, Outcome: "success", Detail: mustJSON(map[string]any{"event_id": review.EventID})})
	})
	return review, err
}

func opaqueSubject(reference string) (string, error) {
	parts := strings.Split(reference, ".")
	if len(parts) != 2 {
		return "", ErrInvalidOpaqueReference
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return "", ErrInvalidOpaqueReference
	}
	values := strings.Split(string(payload), "\n")
	if len(values) != 4 || values[2] == "" {
		return "", ErrInvalidOpaqueReference
	}
	return values[2], nil
}

func (s G8Service) DraftNotification(ctx context.Context, actor entities.Actor, notificationID, instruction string) (map[string]any, error) {
	n, err := s.repository.Notification(ctx, s.db, actor.CenterID, notificationID)
	if err != nil {
		return nil, err
	}
	hash := SourceHash(n.ID, n.CenterID, n.RecipientID, n.Title, n.Body, n.Channel)
	ref, err := s.signer.Sign("draft", actor.CenterID, n.ID, hash)
	if err != nil {
		return nil, err
	}
	result := map[string]any{"draft_id": ref, "notification_id": n.ID, "source_hash": hash, "title": n.Title, "body": n.Body, "degraded": s.assistance == nil}
	if s.assistance == nil {
		return result, nil
	}
	raw, err := s.assistance.DraftNotificationBody(ctx, mustJSON(map[string]any{"center_id": actor.CenterID, "actor_id": actor.ID, "correlation_id": correlationID(ctx), "notification_id": n.ID, "title": n.Title, "source_body": n.Body, "instruction": instruction}))
	if err != nil {
		result["degraded"] = true
		return result, nil
	}
	var ai struct {
		Body     string `json:"body"`
		Degraded bool   `json:"degraded"`
	}
	if json.Unmarshal(raw, &ai) == nil && strings.TrimSpace(ai.Body) != "" {
		result["body"] = ai.Body
		result["degraded"] = ai.Degraded
	}
	return result, nil
}

func (s G8Service) SendDraft(ctx context.Context, actor entities.Actor, draftID, sourceHash, body string) (entities.Notification, error) {
	notificationID, err := opaqueSubject(draftID)
	if err != nil {
		return entities.Notification{}, err
	}
	if _, err = s.signer.Verify(draftID, "draft", actor.CenterID, notificationID, sourceHash); err != nil {
		return entities.Notification{}, err
	}
	source, err := s.repository.Notification(ctx, s.db, actor.CenterID, notificationID)
	if err != nil {
		return entities.Notification{}, err
	}
	if SourceHash(source.ID, source.CenterID, source.RecipientID, source.Title, source.Body, source.Channel) != sourceHash || strings.TrimSpace(body) == "" {
		return entities.Notification{}, ErrInvalidOpaqueReference
	}
	now := time.Now().UTC()
	n := entities.Notification{ID: uuid.NewString(), CenterID: source.CenterID, RecipientID: source.RecipientID, OrderID: source.OrderID, Title: source.Title, Body: body, Channel: source.Channel, Status: "pending", Version: 1, CreatedAt: now}
	err = s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := s.repository.CreateNotification(ctx, tx, n); err != nil {
			return err
		}
		if err := s.repository.CreateDelivery(ctx, tx, uuid.NewString(), n.ID, n.Channel, now); err != nil {
			return err
		}
		if err := s.outbox.Enqueue(ctx, tx, entities.OutboxEvent{ID: uuid.NewString(), EventType: "notification.delivery.requested", AggregateType: "notification", AggregateID: n.ID, Payload: mustJSON(map[string]any{"center_id": n.CenterID, "notification_id": n.ID, "channel": n.Channel}), OccurredAt: now, CreatedAt: now}); err != nil {
			return err
		}
		return s.audit.Append(ctx, tx, AuditEntry{Actor: actor, Action: "notification_draft_sent", EntityType: "notification", EntityID: n.ID, Outcome: "success", Detail: mustJSON(map[string]any{"source_notification_id": source.ID})})
	})
	return n, err
}

func value(v *string) string {
	if v == nil {
		return ""
	}
	return *v
}
func correlationID(ctx context.Context) string {
	if value, ok := ctx.Value("correlation_id").(string); ok {
		return value
	}
	return ""
}
