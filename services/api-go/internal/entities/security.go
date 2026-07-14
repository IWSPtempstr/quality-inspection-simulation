package entities

import "errors"

type Role string

const (
	RoleAdmin     Role = "admin"
	RoleScheduler Role = "scheduler"
	RoleOperator  Role = "operator"
	RoleViewer    Role = "viewer"
)

type Capability string

const (
	CapabilityOrdersRead        Capability = "orders:read"
	CapabilityOrdersWrite       Capability = "orders:write"
	CapabilityResourcesRead     Capability = "resources:read"
	CapabilityScheduleRead      Capability = "schedule:read"
	CapabilityScheduleWrite     Capability = "schedule:write"
	CapabilityExecutionWrite    Capability = "execution:write"
	CapabilityEventsRead        Capability = "events:read"
	CapabilityEventsWrite       Capability = "events:write"
	CapabilityKnowledgeRead     Capability = "knowledge:read"
	CapabilityNotificationsRead Capability = "notifications:read"
	CapabilityAuditRead         Capability = "audit:read"
	CapabilitySystemRead        Capability = "system:read"
)

type Actor struct {
	ID          string
	CenterID    string
	DisplayName string
	Roles       []Role
}

var (
	ErrUnauthenticated     = errors.New("unauthenticated")
	ErrForbidden           = errors.New("forbidden")
	ErrIdempotencyReplay   = errors.New("idempotency key has already been used")
	ErrIdempotencyConflict = errors.New("idempotency key was reused with a different request")
	ErrVersionConflict     = errors.New("version conflict")
)
