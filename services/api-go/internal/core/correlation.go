package core

import (
	"crypto/rand"
	"encoding/hex"
	"net/http"

	"github.com/gin-gonic/gin"
)

const CorrelationIDHeader = "X-Correlation-ID"

func CorrelationMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		correlationID := c.GetHeader(CorrelationIDHeader)
		if correlationID == "" {
			correlationID = newCorrelationID()
		}
		c.Set(CorrelationIDHeader, correlationID)
		c.Header(CorrelationIDHeader, correlationID)
		c.Next()
	}
}

func newCorrelationID() string {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "unavailable"
	}
	return hex.EncodeToString(value[:])
}

func CorrelationID(request *http.Request) string {
	return request.Header.Get(CorrelationIDHeader)
}
