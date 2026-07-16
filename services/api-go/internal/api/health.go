package api

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/detection-center/scheduling-workbench/services/api-go/internal/api/generated"
	"github.com/gin-gonic/gin"
)

// HealthProbe is an injected dependency check. Its error is deliberately not
// returned to callers: health responses expose component state only.
type HealthProbe interface {
	Probe(context.Context) error
}

type HealthProbeFunc func(context.Context) error

func (f HealthProbeFunc) Probe(ctx context.Context) error { return f(ctx) }

type HealthProbes struct {
	Postgres     HealthProbe
	RabbitMQ     HealthProbe
	Redis        HealthProbe
	Partner      HealthProbe
	Notification HealthProbe
}

func (p HealthProbes) handler() gin.HandlerFunc {
	return func(c *gin.Context) {
		services := map[string]string{"api": "available"}
		status := "healthy"
		for _, component := range []struct {
			name     string
			probe    HealthProbe
			critical bool
		}{
			{name: "postgres", probe: p.Postgres, critical: true},
			{name: "rabbitmq", probe: p.RabbitMQ},
			{name: "redis", probe: p.Redis},
			{name: "partner_writeback", probe: p.Partner},
			{name: "notification_channel", probe: p.Notification},
		} {
			if component.probe == nil {
				continue
			}
			if err := component.probe.Probe(c.Request.Context()); err != nil {
				if component.critical {
					services[component.name] = "unavailable"
					status = "unavailable"
				} else {
					services[component.name] = "degraded"
					if status == "healthy" {
						status = "degraded"
					}
				}
				continue
			}
			services[component.name] = "available"
		}
		c.JSON(http.StatusOK, generated.Health{Status: status, Services: services})
	}
}

// HTTPReachabilityProbe verifies that a configured controlled HTTP dependency
// is reachable. HTTP status codes are application responses, not transport
// outages, so only request errors mark the component degraded.
type HTTPReachabilityProbe struct {
	URL    string
	Client *http.Client
}

func (p HTTPReachabilityProbe) Probe(ctx context.Context) error {
	if strings.TrimSpace(p.URL) == "" {
		return fmt.Errorf("endpoint is not configured")
	}
	client := p.Client
	if client == nil {
		client = &http.Client{Timeout: 2 * time.Second}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodOptions, p.URL, nil)
	if err != nil {
		return err
	}
	response, err := client.Do(req)
	if err != nil {
		return err
	}
	return response.Body.Close()
}
