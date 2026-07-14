package api

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api/generated"
)

func TestGeneratedDataQualityFindingPreservesNullableSuggestion(t *testing.T) {
	var withoutSuggestion generated.DataQualityFinding
	if err := json.Unmarshal([]byte(`{"code":"missing_shift","severity":"error","message":"缺少班次","blocking":true,"suggestion":null}`), &withoutSuggestion); err != nil {
		t.Fatalf("unmarshal nullable finding = %v", err)
	}
	if withoutSuggestion.Suggestion != nil {
		t.Fatalf("suggestion = %q, want nil", *withoutSuggestion.Suggestion)
	}

	var withSuggestion generated.DataQualityFinding
	if err := json.Unmarshal([]byte(`{"code":"missing_shift","severity":"error","message":"缺少班次","blocking":true,"suggestion":"补充班次"}`), &withSuggestion); err != nil {
		t.Fatalf("unmarshal finding = %v", err)
	}
	if withSuggestion.Suggestion == nil || *withSuggestion.Suggestion != "补充班次" {
		t.Fatalf("suggestion = %#v, want non-nil generated value", withSuggestion.Suggestion)
	}
}

func TestGeneratedSchedulePreviewRepresentsBothFallbackBranches(t *testing.T) {
	for _, body := range []string{
		`{"fallback_used":false,"fallback_reason":null}`,
		`{"fallback_used":true,"fallback_reason":"cp_sat_infeasible"}`,
	} {
		var preview generated.SchedulePreview
		if err := json.Unmarshal([]byte(body), &preview); err != nil {
			t.Fatalf("unmarshal fallback branch %s = %v", body, err)
		}
		if preview.FallbackUsed && preview.FallbackReason == nil {
			t.Fatalf("fallback branch lost fallback_reason: %#v", preview)
		}
		if !preview.FallbackUsed && preview.FallbackReason != nil {
			t.Fatalf("non-fallback branch lost nullable fallback_reason: %#v", preview)
		}
	}
}

func TestGeneratedFallbackBranchTypesAndNullSupportRemainStronglyTyped(t *testing.T) {
	for _, branch := range []any{generated.SchedulePreviewOneOf{}, generated.SchedulePreviewOneOf1{}} {
		field, found := reflect.TypeOf(branch).FieldByName("FallbackUsed")
		if !found || field.Type != reflect.TypeFor[bool]() {
			t.Fatalf("FallbackUsed type = %v, want bool", field.Type)
		}
	}

	encoded, err := json.Marshal(generated.Null{})
	if err != nil || string(encoded) != "null" {
		t.Fatalf("marshal Null = %q, %v; want null", encoded, err)
	}
	var null generated.Null
	if err := json.Unmarshal([]byte(`"not-null"`), &null); err == nil {
		t.Fatal("unmarshal non-null into Null error = nil, want error")
	}
}

func TestGeneratedProblemRetainsRFC9457Fields(t *testing.T) {
	var problem generated.Problem
	if err := json.Unmarshal([]byte(`{"type":"urn:problem:conflict","title":"版本冲突","status":409,"detail":"请刷新后重试","instance":"/api/v1/orders/O-1"}`), &problem); err != nil {
		t.Fatalf("unmarshal problem = %v", err)
	}
	if problem.Type != "urn:problem:conflict" || problem.Status != 409 || problem.Instance != "/api/v1/orders/O-1" {
		t.Fatalf("problem = %#v, want RFC 9457 fields", problem)
	}
}
