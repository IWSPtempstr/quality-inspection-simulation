package services

import (
	"context"
	"encoding/json"
)

// AssistanceClient deliberately exposes only the six contract-mapped calls.
// Its inputs are constructed by Go from persisted, center-scoped facts.
type AssistanceClient interface {
	Diagnose(context.Context, json.RawMessage) (json.RawMessage, error)
	ExplainSchedule(context.Context, json.RawMessage) (json.RawMessage, error)
	ExplainDataQuality(context.Context, json.RawMessage) (json.RawMessage, error)
	CreateCaseCandidate(context.Context, json.RawMessage) (json.RawMessage, error)
	SuggestAuditFilters(context.Context, json.RawMessage) (json.RawMessage, error)
	DraftNotificationBody(context.Context, json.RawMessage) (json.RawMessage, error)
}
