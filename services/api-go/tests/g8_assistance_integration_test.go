package tests

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/models"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/services"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

const (
	g8Center = "center-g8"
	g8Actor  = "scheduler-g8"
	g8Token  = "g8-integration-token"
)

func TestG8PostgresCaseReviewAndDraftBoundary(t *testing.T) {
	_, db := g6RepairDatabase(t)
	assertG8Migration(t, db)
	eventID, notificationID := seedG8ClosedEventAndNotification(t, db, g8Center)
	router := g8Router(db, g8Center)

	t.Run("candidate and draft reads are signed center-scoped and non-persistent", func(t *testing.T) {
		before := g8ReadPersistenceCounts(t, db)
		candidate := g8Request(t, router, http.MethodPost, "/api/v1/events/"+eventID+"/case-candidates", nil, "", "")
		if candidate.Code != http.StatusOK {
			t.Fatalf("create candidate = %d: %s", candidate.Code, candidate.Body.String())
		}
		var candidateBody struct {
			CandidateID string `json:"candidate_id"`
			SourceHash  string `json:"source_candidate_hash"`
		}
		if err := json.Unmarshal(candidate.Body.Bytes(), &candidateBody); err != nil || candidateBody.CandidateID == "" || candidateBody.SourceHash == "" {
			t.Fatalf("decode signed candidate = (%#v, %v)", candidateBody, err)
		}
		draft := g8Request(t, router, http.MethodPost, "/api/v1/notification-drafts", []byte(`{"notification_id":"`+notificationID+`","instruction":"clarify"}`), "", "")
		if draft.Code != http.StatusOK {
			t.Fatalf("create draft = %d: %s", draft.Code, draft.Body.String())
		}
		var draftBody struct {
			DraftID    string `json:"draft_id"`
			SourceHash string `json:"source_hash"`
		}
		if err := json.Unmarshal(draft.Body.Bytes(), &draftBody); err != nil || draftBody.DraftID == "" || draftBody.SourceHash == "" {
			t.Fatalf("decode signed draft = (%#v, %v)", draftBody, err)
		}
		if after := g8ReadPersistenceCounts(t, db); after != before {
			t.Fatalf("candidate/draft reads persisted data: before=%#v after=%#v", before, after)
		}

		otherRouter := g8Router(db, "other-center")
		foreign := g8Request(t, otherRouter, http.MethodPost, "/api/v1/exception-case-candidates/"+candidateBody.CandidateID+"/submit", g8CaseSubmission(candidateBody.SourceHash), "candidate-cross-center", "1")
		if foreign.Code != http.StatusConflict {
			t.Fatalf("cross-center candidate submit = %d: %s", foreign.Code, foreign.Body.String())
		}
	})

	t.Run("candidate submission stores exactly one review audit and outbox record with byte-exact replay", func(t *testing.T) {
		candidate := g8Request(t, router, http.MethodPost, "/api/v1/events/"+eventID+"/case-candidates", nil, "", "")
		var result struct {
			CandidateID string `json:"candidate_id"`
			SourceHash  string `json:"source_candidate_hash"`
		}
		if err := json.Unmarshal(candidate.Body.Bytes(), &result); err != nil {
			t.Fatalf("decode candidate: %v", err)
		}
		body := g8CaseSubmission(result.SourceHash)
		first := g8Request(t, router, http.MethodPost, "/api/v1/exception-case-candidates/"+result.CandidateID+"/submit", body, "case-submit", "1")
		if first.Code != http.StatusCreated {
			t.Fatalf("submit candidate = %d: %s", first.Code, first.Body.String())
		}
		replay := g8Request(t, router, http.MethodPost, "/api/v1/exception-case-candidates/"+result.CandidateID+"/submit", body, "case-submit", "1")
		if replay.Code != first.Code || !bytes.Equal(replay.Body.Bytes(), first.Body.Bytes()) {
			t.Fatalf("candidate replay = (%d, %s), want (%d, %s)", replay.Code, replay.Body.String(), first.Code, first.Body.String())
		}
		changed := append([]byte(nil), body...)
		changed = bytes.Replace(changed, []byte(`"summary":"fixture summary"`), []byte(`"summary":"changed summary"`), 1)
		conflict := g8Request(t, router, http.MethodPost, "/api/v1/exception-case-candidates/"+result.CandidateID+"/submit", changed, "case-submit", "1")
		if conflict.Code != http.StatusConflict {
			t.Fatalf("changed candidate replay = %d: %s", conflict.Code, conflict.Body.String())
		}
		assertG8Counts(t, db, 1, 1, 1)
	})

	t.Run("draft send persists delivery boundary and replays first response", func(t *testing.T) {
		draft := g8Request(t, router, http.MethodPost, "/api/v1/notification-drafts", []byte(`{"notification_id":"`+notificationID+`","instruction":"clarify"}`), "", "")
		var result struct {
			DraftID    string `json:"draft_id"`
			SourceHash string `json:"source_hash"`
		}
		if err := json.Unmarshal(draft.Body.Bytes(), &result); err != nil {
			t.Fatalf("decode draft: %v", err)
		}
		body := []byte(`{"source_hash":"` + result.SourceHash + `","body":"edited notification body"}`)
		first := g8Request(t, router, http.MethodPost, "/api/v1/notification-drafts/"+result.DraftID+"/send", body, "draft-send", "1")
		if first.Code != http.StatusAccepted {
			t.Fatalf("send draft = %d: %s", first.Code, first.Body.String())
		}
		replay := g8Request(t, router, http.MethodPost, "/api/v1/notification-drafts/"+result.DraftID+"/send", body, "draft-send", "1")
		if replay.Code != first.Code || !bytes.Equal(replay.Body.Bytes(), first.Body.Bytes()) {
			t.Fatalf("draft replay = (%d, %s), want (%d, %s)", replay.Code, replay.Body.String(), first.Code, first.Body.String())
		}
		var deliveries int64
		if err := db.Model(&models.NotificationDelivery{}).Where("notification_id IN (SELECT id FROM notifications WHERE center_id = ?)", g8Center).Count(&deliveries).Error; err != nil {
			t.Fatalf("count notification deliveries: %v", err)
		}
		if deliveries != 2 { // source notification plus the deterministic sent-draft notification
			t.Fatalf("notification deliveries = %d, want 2", deliveries)
		}
	})
}

func TestG8CaseSubmissionRollsBackOnOutboxFailure(t *testing.T) {
	ctx, db := g6RepairDatabase(t)
	eventID, _ := seedG8ClosedEventAndNotification(t, db, g8Center)
	service := services.NewG8Service(db, nil, services.NewOpaqueReferenceSigner(g8Token))
	actor := entities.Actor{ID: g8Actor, CenterID: g8Center, Roles: []entities.Role{entities.RoleScheduler}}
	candidate, err := service.Candidate(ctx, actor, eventID)
	if err != nil {
		t.Fatalf("create candidate: %v", err)
	}
	candidateID, _ := candidate["candidate_id"].(string)
	sourceHash, _ := candidate["source_candidate_hash"].(string)
	if err := db.Exec(`CREATE FUNCTION reject_g8_outbox() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'forced G8 outbox failure'; END; $$ LANGUAGE plpgsql`).Error; err != nil {
		t.Fatalf("create test outbox trigger function: %v", err)
	}
	if err := db.Exec(`CREATE TRIGGER reject_g8_outbox_trigger BEFORE INSERT ON outbox_events FOR EACH ROW WHEN (NEW.event_type = 'exception_case.review_submitted') EXECUTE FUNCTION reject_g8_outbox()`).Error; err != nil {
		t.Fatalf("create test outbox trigger: %v", err)
	}
	_, err = service.SubmitCase(ctx, actor, candidateID, map[string]any{"source_candidate_hash": sourceHash, "summary": "fixture summary", "trigger": "fixture trigger", "impact": "fixture impact", "disposition": "handled", "outcome": "fixture outcome", "tags": []string{"fixture"}, "retention_until": time.Now().UTC().Add(time.Hour)})
	if err == nil {
		t.Fatal("submit candidate with rejected outbox = nil, want transaction error")
	}
	assertG8Counts(t, db, 0, 0, 0)
}

func assertG8Migration(t *testing.T, db *gorm.DB) {
	t.Helper()
	if !db.Migrator().HasTable(&models.ExceptionCaseReview{}) {
		t.Fatal("migration 00006 did not create exception_case_reviews")
	}
	for _, column := range []string{"center_id", "event_id", "source_candidate_hash", "submission", "retention_until", "status", "version"} {
		if !db.Migrator().HasColumn(&models.ExceptionCaseReview{}, column) {
			t.Fatalf("migration 00006 missing exception_case_reviews.%s", column)
		}
	}
}

type g8Counts struct{ reviews, audits, outbox int64 }

type g8ReadCounts struct {
	reviews, audits, outbox, notifications, deliveries, idempotency int64
}

func g8ReadPersistenceCounts(t *testing.T, db *gorm.DB) g8ReadCounts {
	t.Helper()
	base := g8PersistenceCounts(t, db)
	counts := g8ReadCounts{reviews: base.reviews, audits: base.audits, outbox: base.outbox}
	for _, target := range []struct {
		model any
		into  *int64
	}{
		{&models.Notification{}, &counts.notifications},
		{&models.NotificationDelivery{}, &counts.deliveries},
		{&models.IdempotencyRecord{}, &counts.idempotency},
	} {
		if err := db.Model(target.model).Count(target.into).Error; err != nil {
			t.Fatalf("count %T: %v", target.model, err)
		}
	}
	return counts
}

func g8PersistenceCounts(t *testing.T, db *gorm.DB) g8Counts {
	t.Helper()
	var counts g8Counts
	if err := db.Model(&models.ExceptionCaseReview{}).Count(&counts.reviews).Error; err != nil {
		t.Fatalf("count reviews: %v", err)
	}
	if err := db.Model(&models.AuditLog{}).Count(&counts.audits).Error; err != nil {
		t.Fatalf("count audit logs: %v", err)
	}
	if err := db.Model(&models.OutboxEvent{}).Count(&counts.outbox).Error; err != nil {
		t.Fatalf("count outbox: %v", err)
	}
	return counts
}

func assertG8Counts(t *testing.T, db *gorm.DB, reviews, audits, outbox int64) {
	t.Helper()
	actual := g8PersistenceCounts(t, db)
	if actual != (g8Counts{reviews: reviews, audits: audits, outbox: outbox}) {
		t.Fatalf("G8 persistence counts = %#v, want reviews=%d audits=%d outbox=%d", actual, reviews, audits, outbox)
	}
}

func seedG8ClosedEventAndNotification(t *testing.T, db *gorm.DB, center string) (string, string) {
	t.Helper()
	now := time.Now().UTC()
	eventID, notificationID := uuid.NewString(), uuid.NewString()
	if err := db.Create(&models.SystemEvent{ID: eventID, CenterID: center, EventType: "execution.anomaly", EntityType: "order", Severity: "warning", Status: "closed", Payload: []byte(`{"reason":"fixture"}`), Disposition: ptr("handled"), Version: 1, OccurredAt: now, CreatedAt: now, UpdatedAt: now}).Error; err != nil {
		t.Fatalf("seed closed event: %v", err)
	}
	if err := db.Create(&models.Notification{ID: notificationID, CenterID: center, RecipientID: g8Actor, Title: "fixture", Body: "original body", Channel: "in_app", Status: "pending", Version: 1, CreatedAt: now, UpdatedAt: now}).Error; err != nil {
		t.Fatalf("seed source notification: %v", err)
	}
	if err := db.Create(&models.NotificationDelivery{ID: uuid.NewString(), NotificationID: notificationID, Channel: "in_app", Status: "pending", CreatedAt: now, UpdatedAt: now}).Error; err != nil {
		t.Fatalf("seed source notification delivery: %v", err)
	}
	return eventID, notificationID
}

func g8Router(db *gorm.DB, center string) *gin.Engine {
	return api.NewRouterWithG8(slog.New(slog.NewTextHandler(io.Discard, nil)), db, &g6RepairLocker{}, g8Token, api.HealthProbes{}, nil, api.AuthenticatorFunc(func(context.Context, string) (entities.Actor, error) {
		return entities.Actor{ID: g8Actor, CenterID: center, Roles: []entities.Role{entities.RoleScheduler}}, nil
	}))
}

func g8Request(t *testing.T, router http.Handler, method, path string, body []byte, key, version string) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, path, bytes.NewReader(body))
	if key != "" {
		request.Header.Set("Idempotency-Key", key)
	}
	if version != "" {
		request.Header.Set("If-Match", version)
	}
	request.AddCookie(&http.Cookie{Name: api.SessionCookieName, Value: "g8-session"})
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	return response
}

func g8CaseSubmission(sourceHash string) []byte {
	return []byte(`{"source_candidate_hash":"` + sourceHash + `","summary":"fixture summary","trigger":"fixture trigger","impact":"fixture impact","disposition":"handled","outcome":"fixture outcome","tags":["fixture"],"retention_until":"2030-01-01T00:00:00Z"}`)
}

func ptr(value string) *string { return &value }
