package models

import (
	"gorm.io/datatypes"
	"time"
)

type DetectionProject struct {
	ID, SourceID, Code, Name   string
	Active                     bool
	SourceVersion              int64
	EffectiveFrom, EffectiveTo *time.Time
	CreatedAt, UpdatedAt       time.Time
}

func (DetectionProject) TableName() string { return "detection_projects" }

type ProjectCertificationType struct{ ProjectID, CertificationType string }

func (ProjectCertificationType) TableName() string { return "project_certification_types" }

type CenterProject struct {
	CenterID, ProjectID        string
	Active                     bool
	SourceVersion              int64
	EffectiveFrom, EffectiveTo *time.Time
}

func (CenterProject) TableName() string { return "center_projects" }

type Order struct {
	ID, CenterID, SampleName    string
	SampleQuantity              int
	CertificationType, Priority string
	PromisedFinishTime          time.Time
	Status                      string
	Version                     int64
	SourceOrderID               *string
	PauseReason                 *string
	CreatedBy, UpdatedBy        string
	CreatedAt, UpdatedAt        time.Time
}

func (Order) TableName() string { return "orders" }

type OrderProject struct {
	ID, OrderID, ProjectID, Status      string
	SourceOrderProjectID, RetestOrderID *string
	Version                             int64
}

func (OrderProject) TableName() string { return "order_projects" }

type Equipment struct {
	ID, CenterID, SourceID, Name, Status string
	Capacity                             int
	Active                               bool
	SourceVersion                        int64
	CreatedAt, UpdatedAt                 time.Time
}

func (Equipment) TableName() string { return "equipment" }

type Employee struct {
	ID, CenterID, SourceID, Name string
	Active                       bool
	SourceVersion                int64
	CreatedAt, UpdatedAt         time.Time
}

func (Employee) TableName() string { return "employees" }

type Shift struct {
	ID, CenterID, SourceID, Name string
	StartTime, EndTime           time.Time
	Active                       bool
	SourceVersion                int64
}

func (Shift) TableName() string { return "shifts" }

type Unavailability struct {
	ID, CenterID, SourceID, EntityID, Reason string
	StartsAt, EndsAt                         time.Time
	Active                                   bool
	SourceVersion                            int64
}

func (Unavailability) TableName() string { return "unavailability" }

var _ = datatypes.JSON{}
