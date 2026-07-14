package services

import "github.com/detection-center/scheduling-workbench/services/api-go/internal/entities"

var roleCapabilities = map[entities.Role]map[entities.Capability]struct{}{
	entities.RoleAdmin: {},
	entities.RoleScheduler: {
		entities.CapabilityOrdersRead: {}, entities.CapabilityOrdersWrite: {}, entities.CapabilityResourcesRead: {},
		entities.CapabilityScheduleRead: {}, entities.CapabilityScheduleWrite: {}, entities.CapabilityEventsRead: {},
		entities.CapabilityEventsWrite: {}, entities.CapabilityKnowledgeRead: {}, entities.CapabilityNotificationsRead: {},
		entities.CapabilityAuditRead: {},
	},
	entities.RoleOperator: {
		entities.CapabilityExecutionWrite: {}, entities.CapabilityNotificationsRead: {},
	},
	entities.RoleViewer: {
		entities.CapabilityOrdersRead: {}, entities.CapabilityResourcesRead: {}, entities.CapabilityScheduleRead: {},
		entities.CapabilityEventsRead: {}, entities.CapabilityKnowledgeRead: {}, entities.CapabilityNotificationsRead: {},
	},
}

func Authorize(actor entities.Actor, required entities.Capability) error {
	for _, role := range actor.Roles {
		if role == entities.RoleAdmin {
			return nil
		}
		if _, allowed := roleCapabilities[role][required]; allowed {
			return nil
		}
	}
	return entities.ErrForbidden
}

func PrimaryRole(actor entities.Actor) (entities.Role, error) {
	for _, candidate := range []entities.Role{entities.RoleAdmin, entities.RoleScheduler, entities.RoleOperator, entities.RoleViewer} {
		for _, role := range actor.Roles {
			if role == candidate {
				return role, nil
			}
		}
	}
	return "", entities.ErrForbidden
}
