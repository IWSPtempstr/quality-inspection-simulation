package entities

import (
	"encoding/json"
	"time"
)

type ExceptionCaseReview struct {
	ID, CenterID, EventID, SubmittedBy, SourceCandidateHash, Status string
	Submission                                                      json.RawMessage
	RetentionUntil, SubmittedAt                                     time.Time
	Version                                                         int64
}
