package services

import "testing"

func TestNormalizeCandidateForTestVector(t *testing.T) {
	candidate := map[string]any{
		"input_hash":      "sha256:vector",
		"algorithm_used":  "cp_sat",
		"solver_status":   "optimal",
		"fallback_used":   false,
		"fallback_reason": nil,
		"blocked_steps":   []any{},
		"schedule": map[string]any{
			"steps": []map[string]any{{
				"id":         "step-1",
				"order_id":   "order-1",
				"project_id": "project-1",
				"starts_at":  "2026-07-16T08:00:00+08:00",
				"ends_at":    "2026-07-16T08:30:00+08:00",
			}},
		},
		"metrics": map[string]any{
			"scheduled_step_count": 1,
			"blocked_step_count":   0,
		},
	}

	hash, steps, err := NormalizeCandidateForTest(candidate)
	if err != nil {
		t.Fatalf("NormalizeCandidateForTest error = %v", err)
	}
	if hash != "sha256:ffcea49f1eb07a54c58f3861f279e934060dfb5c0e819b31c9fd8e6118d6a19e" {
		t.Fatalf("hash = %q", hash)
	}
	if string(steps) != `[{"ends_at":"2026-07-16T08:30:00+08:00","id":"step-1","order_id":"order-1","project_id":"project-1","starts_at":"2026-07-16T08:00:00+08:00"}]` {
		t.Fatalf("steps = %s", steps)
	}
}
