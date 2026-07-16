package services

import (
	"testing"
)

func TestOpaqueReferenceRejectsCenterOrPayloadTampering(t *testing.T) {
	signer := NewOpaqueReferenceSigner("test-secret")
	value, err := signer.Sign("case", "center-a", "event-1", "sha256:source")
	if err != nil {
		t.Fatalf("sign reference: %v", err)
	}
	if _, err := signer.Verify(value, "case", "center-b", "event-1", "sha256:source"); err == nil {
		t.Fatal("Verify accepted a reference for another center")
	}
	if _, err := signer.Verify(value+"x", "case", "center-a", "event-1", "sha256:source"); err == nil {
		t.Fatal("Verify accepted a tampered reference")
	}
}

func TestValidateAuditFiltersRejectsUnapprovedFieldAndOperator(t *testing.T) {
	valid := []AuditFilter{{Field: "action", Operator: "contains", Value: "closed"}}
	if err := ValidateAuditFilters(valid); err != nil {
		t.Fatalf("ValidateAuditFilters(valid): %v", err)
	}
	if err := ValidateAuditFilters([]AuditFilter{{Field: "center_id", Operator: "equals", Value: "center-b"}}); err == nil {
		t.Fatal("ValidateAuditFilters accepted a center filter")
	}
	if err := ValidateAuditFilters([]AuditFilter{{Field: "action", Operator: "delete", Value: "x"}}); err == nil {
		t.Fatal("ValidateAuditFilters accepted an unknown operator")
	}
}
