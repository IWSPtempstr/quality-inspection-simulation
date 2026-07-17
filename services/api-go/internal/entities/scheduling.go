package entities

import (
	"encoding/json"
	"time"
)

const (
	PreviewPendingCandidate         = "pending_candidate"
	PreviewPendingReview            = "pending_review"
	PreviewRejected                 = "rejected"
	PreviewApprovedPendingWriteback = "approved_pending_writeback"
	PreviewApproved                 = "approved"
	PreviewConflicted               = "conflicted"
	PreviewFailed                   = "failed"
)

type ScheduleSnapshot struct {
	ID, CenterID, InputHash                      string
	AsOf                                         time.Time
	BaseScheduleVersion, ResourceSnapshotVersion int64
	Payload                                      json.RawMessage
	CreatedAt                                    time.Time
}
type SchedulePreview struct {
	ID, CenterID, SnapshotID, Status string
	NormalizedResultHash             *string
	Candidate, NormalizedSteps       json.RawMessage
	Version                          int64
	PartnerFailure                   *string
	CreatedAt, UpdatedAt             time.Time
}
type ScheduleVersion struct {
	ID, CenterID, PreviewID string
	Version                 int64
	Steps                   json.RawMessage
	CreatedAt               time.Time
}
