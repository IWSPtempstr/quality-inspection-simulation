package models

import (
	"time"

	"gorm.io/datatypes"
)

type ExceptionCaseReview struct {
	ID, CenterID, EventID, SubmittedBy, SourceCandidateHash, Status string
	Submission                                                      datatypes.JSON
	RetentionUntil, SubmittedAt, CreatedAt                          time.Time
	Version                                                         int64
}

func (ExceptionCaseReview) TableName() string { return "exception_case_reviews" }
