package tests

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/clients/postgres"
	"github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

const shiftsRouteTestCenter = "center-shifts-route"

func TestG4ListShiftsReadsPostgresTimeValuesAndIsCenterScoped(t *testing.T) {
	ctx, db := g4ShiftsRouteDatabase(t)
	seedG4RouteShift(t, ctx, db, "00000000-0000-0000-0000-000000000701", shiftsRouteTestCenter, "day-shift", "08:15:00", "16:45:00")
	seedG4RouteShift(t, ctx, db, "00000000-0000-0000-0000-000000000702", "other-center", "other-shift", "09:00:00", "17:00:00")

	request := httptest.NewRequest(http.MethodGet, "/api/v1/resources/shifts", nil)
	request.AddCookie(&http.Cookie{Name: api.SessionCookieName, Value: "deterministic-session"})
	response := httptest.NewRecorder()
	g4ShiftsRouteRouter(db).ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("GET /api/v1/resources/shifts status = %d, want %d; body = %s", response.Code, http.StatusOK, response.Body.String())
	}
	var shifts []struct {
		ID        string `json:"id"`
		Name      string `json:"name"`
		StartTime string `json:"start_time"`
		EndTime   string `json:"end_time"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &shifts); err != nil {
		t.Fatalf("decode shift response: %v", err)
	}
	if len(shifts) != 1 {
		t.Fatalf("returned shifts = %#v, want only the authenticated center shift", shifts)
	}
	if got := shifts[0]; got.ID != "00000000-0000-0000-0000-000000000701" || got.Name != "day-shift" || got.StartTime != "08:15:00" || got.EndTime != "16:45:00" {
		t.Fatalf("returned shift = %#v, want exact PostgreSQL TIME strings for center shift", got)
	}
}

func g4ShiftsRouteDatabase(t *testing.T) (context.Context, *gorm.DB) {
	t.Helper()
	ctx := context.Background()
	container, databaseURL := startPostgres(t, ctx)
	t.Cleanup(func() { _ = container.Terminate(ctx) })
	db, err := postgres.Open(ctx, databaseURL)
	if err != nil {
		t.Fatalf("open PostgreSQL test database: %v", err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatalf("get PostgreSQL test database: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })
	if err := postgres.Migrate(ctx, sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("migrate PostgreSQL test database: %v", err)
	}
	return ctx, db
}

func seedG4RouteShift(t *testing.T, ctx context.Context, db *gorm.DB, id, centerID, name, startTime, endTime string) {
	t.Helper()
	const query = `INSERT INTO shifts (id, center_id, source_id, name, start_time, end_time, active, source_version)
		VALUES (?, ?, ?, ?, ?::time, ?::time, true, 1)`
	if err := db.WithContext(ctx).Exec(query, id, centerID, "source-"+id, name, startTime, endTime).Error; err != nil {
		t.Fatalf("seed shift %s: %v", id, err)
	}
}

func g4ShiftsRouteRouter(db *gorm.DB) *gin.Engine {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	return api.NewRouterWithDatabase(logger, db, api.AuthenticatorFunc(func(context.Context, string) (entities.Actor, error) {
		return entities.Actor{ID: "scheduler-shifts-route", CenterID: shiftsRouteTestCenter, Roles: []entities.Role{entities.RoleScheduler}}, nil
	}))
}
