package entities

import "time"

type OrderInput struct {
	SampleName                  string
	SampleQuantity              int
	CertificationType, Priority string
	PromisedFinishTime          time.Time
	ProjectIDs                  []string
}
type OrderPatch struct {
	SampleName         *string    `json:"sample_name"`
	SampleQuantity     *int       `json:"sample_quantity"`
	CertificationType  *string    `json:"certification_type"`
	Priority           *string    `json:"priority"`
	PromisedFinishTime *time.Time `json:"promised_finish_time"`
	ProjectIDs         *[]string  `json:"project_ids"`
}
type OrderResult struct {
	ID, SampleName, CertificationType, Priority, Status string
	SampleQuantity                                      int
	PromisedFinishTime, CreatedAt                       time.Time
	ProjectIDs                                          []string
	Version                                             int64
}
