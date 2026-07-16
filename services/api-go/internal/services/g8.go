package services

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"strings"
)

var ErrInvalidOpaqueReference = errors.New("invalid opaque reference")

// OpaqueReferenceSigner creates stateless, center-bound references for the
// non-persistent candidate and draft responses defined by the public contract.
type OpaqueReferenceSigner struct{ secret []byte }

func NewOpaqueReferenceSigner(secret string) OpaqueReferenceSigner {
	return OpaqueReferenceSigner{secret: []byte(secret)}
}

func (s OpaqueReferenceSigner) Sign(kind, centerID, subjectID, sourceHash string) (string, error) {
	if len(s.secret) == 0 || kind == "" || centerID == "" || subjectID == "" || sourceHash == "" {
		return "", ErrInvalidOpaqueReference
	}
	payload := strings.Join([]string{kind, centerID, subjectID, sourceHash}, "\n")
	mac := hmac.New(sha256.New, s.secret)
	_, _ = mac.Write([]byte(payload))
	return base64.RawURLEncoding.EncodeToString([]byte(payload)) + "." + hex.EncodeToString(mac.Sum(nil)), nil
}

func (s OpaqueReferenceSigner) Verify(value, kind, centerID, subjectID, sourceHash string) (string, error) {
	parts := strings.Split(value, ".")
	if len(parts) != 2 || len(s.secret) == 0 {
		return "", ErrInvalidOpaqueReference
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return "", ErrInvalidOpaqueReference
	}
	mac := hmac.New(sha256.New, s.secret)
	_, _ = mac.Write(payload)
	expected, err := hex.DecodeString(parts[1])
	if err != nil || !hmac.Equal(expected, mac.Sum(nil)) {
		return "", ErrInvalidOpaqueReference
	}
	values := strings.Split(string(payload), "\n")
	if len(values) != 4 || values[0] != kind || values[1] != centerID || values[2] != subjectID || values[3] != sourceHash {
		return "", ErrInvalidOpaqueReference
	}
	return values[3], nil
}

type AuditFilter struct {
	Field    string `json:"field"`
	Operator string `json:"operator"`
	Value    string `json:"value"`
}

func ValidateAuditFilters(filters []AuditFilter) error {
	allowedFields := map[string]bool{"actor_id": true, "action": true, "entity_id": true, "created_at": true}
	allowedOperators := map[string]bool{"equals": true, "contains": true, "gte": true, "lte": true}
	for _, filter := range filters {
		if !allowedFields[filter.Field] || !allowedOperators[filter.Operator] || strings.TrimSpace(filter.Value) == "" {
			return fmt.Errorf("invalid audit filter")
		}
	}
	return nil
}

func SourceHash(parts ...string) string {
	sort.Strings(parts)
	sum := sha256.Sum256([]byte(strings.Join(parts, "\n")))
	return "sha256:" + hex.EncodeToString(sum[:])
}
