package services

import (
	"testing"
)

func TestParseResourceEventRejectsUnsupportedAndIncompleteEnvelopes(t *testing.T) {
	valid := []byte(`{"event_id":"event-1","center_id":"center-1","event_type":"upserted","entity_type":"equipment","entity_id":"equipment-1","source_version":1,"occurred_at":"2026-07-15T08:00:00Z","payload":{"name":"Line 1","status":"available","capacity":1}}`)
	if _, err := parseResourceEvent(valid); err != nil {
		t.Fatalf("parse valid event: %v", err)
	}
	for _, raw := range [][]byte{
		[]byte(`{"event_id":"event-1"}`),
		[]byte(`{"event_id":"event-1","center_id":"center-1","event_type":"upserted","entity_type":"project","entity_id":"id","source_version":1,"occurred_at":"2026-07-15T08:00:00Z","payload":{}}`),
		[]byte(`{"event_id":"event-1","center_id":"center-1","event_type":"deleted","entity_type":"equipment","entity_id":"id","source_version":1,"occurred_at":"2026-07-15T08:00:00Z","payload":{}}`),
		[]byte(`{"event_id":"event-1","center_id":"center-1","event_type":"upserted","entity_type":"equipment","entity_id":"id","source_version":1,"occurred_at":"2026-07-15T08:00:00Z","payload":{"name":"missing capacity","status":"available"}}`),
	} {
		if _, err := parseResourceEvent(raw); err == nil {
			t.Fatalf("parseResourceEvent(%s) error = nil", raw)
		}
	}
}
