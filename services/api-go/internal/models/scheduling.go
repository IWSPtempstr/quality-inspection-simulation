package models

import (
	"gorm.io/datatypes"
	"time"
)

type ScheduleSnapshot struct {
	ID                      string `gorm:"type:uuid;primaryKey"`
	CenterID                string
	InputHash               string
	AsOf                    time.Time
	BaseScheduleVersion     int64
	ResourceSnapshotVersion int64
	Payload                 datatypes.JSON `gorm:"type:jsonb"`
	CreatedAt               time.Time
}

func (ScheduleSnapshot) TableName() string { return "schedule_snapshots" }

type SchedulePreview struct {
	ID                           string `gorm:"type:uuid;primaryKey"`
	CenterID, SnapshotID, Status string
	NormalizedResultHash         *string
	Candidate, NormalizedSteps   datatypes.JSON `gorm:"type:jsonb"`
	Version                      int64
	PartnerFailure               *string
	CreatedAt, UpdatedAt         time.Time
}

func (SchedulePreview) TableName() string { return "schedule_previews" }

type ScheduleVersion struct {
	ID        string `gorm:"type:uuid;primaryKey"`
	CenterID  string
	Version   int64
	PreviewID string
	Steps     datatypes.JSON `gorm:"type:jsonb"`
	CreatedAt time.Time
}

func (ScheduleVersion) TableName() string { return "schedule_versions" }
