package handler

import (
	"context"
	"net/http"
	"time"

	"github.com/dkyyyy/paper-agent/gateway/internal/service"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

// HealthHandler handles the /health endpoint.
type HealthHandler struct {
	rdb         *redis.Client
	agentClient *service.AgentClient
	startTime   time.Time
}

// NewHealthHandler creates a health handler.
func NewHealthHandler(rdb *redis.Client, agentClient *service.AgentClient) *HealthHandler {
	return &HealthHandler{
		rdb:         rdb,
		agentClient: agentClient,
		startTime:   time.Now(),
	}
}

// Health handles GET /health.
func (h *HealthHandler) Health(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
	defer cancel()

	services := make(map[string]string)

	if err := h.rdb.Ping(ctx).Err(); err != nil {
		services["redis"] = "disconnected"
	} else {
		services["redis"] = "connected"
	}

	resp, err := h.agentClient.HealthCheck(ctx)
	if err != nil {
		services["agent_service"] = "disconnected"
	} else if resp.Healthy {
		services["agent_service"] = "connected"
	} else {
		services["agent_service"] = "unhealthy"
	}

	status := "ok"
	for _, v := range services {
		if v != "connected" {
			status = "degraded"
			break
		}
	}

	uptime := time.Since(h.startTime).Round(time.Second).String()

	c.JSON(http.StatusOK, gin.H{
		"status":   status,
		"services": services,
		"uptime":   uptime,
	})
}
