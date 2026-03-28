# Codex 执行指令 — 任务 2.6：健康检查与中间件

## 任务目标

实现健康检查端点（检测 Redis、Agent、PostgreSQL 连通性）、CORS、请求日志、限流中间件。

## 前置依赖

- 任务 2.1 ~ 2.5 已完成
- 参考文档：`docs/04-api-design.md` 健康检查接口

## 需要创建的文件

### 1. `gateway/internal/handler/health.go`

```go
package handler

import (
	"context"
	"net/http"
	"time"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/dkyyyy/paper-agent/gateway/internal/service"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

type HealthHandler struct {
	rdb         *redis.Client
	agentClient *service.AgentClient
	startTime   time.Time
}

func NewHealthHandler(rdb *redis.Client, agentClient *service.AgentClient) *HealthHandler {
	return &HealthHandler{
		rdb:         rdb,
		agentClient: agentClient,
		startTime:   time.Now(),
	}
}

// Health handles GET /health
func (h *HealthHandler) Health(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
	defer cancel()

	services := make(map[string]string)

	// Check Redis
	if err := h.rdb.Ping(ctx).Err(); err != nil {
		services["redis"] = "disconnected"
	} else {
		services["redis"] = "connected"
	}

	// Check Agent Service
	resp, err := h.agentClient.HealthCheck(ctx)
	if err != nil {
		services["agent_service"] = "disconnected"
	} else if resp.Healthy {
		services["agent_service"] = "connected"
	} else {
		services["agent_service"] = "unhealthy"
	}

	// Overall status
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
```

### 2. `gateway/internal/handler/session.go`

```go
package handler

import (
	"net/http"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/dkyyyy/paper-agent/gateway/internal/service"
	"github.com/gin-gonic/gin"
)

type SessionHandler struct {
	sessionSvc service.SessionService
}

func NewSessionHandler(sessionSvc service.SessionService) *SessionHandler {
	return &SessionHandler{sessionSvc: sessionSvc}
}

// Create handles POST /api/v1/sessions
func (h *SessionHandler) Create(c *gin.Context) {
	sess, err := h.sessionSvc.Create(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "failed to create session"})
		return
	}
	c.JSON(http.StatusOK, model.Response{Code: 0, Data: gin.H{
		"session_id": sess.ID,
		"created_at": sess.CreatedAt,
	}})
}

// List handles GET /api/v1/sessions
func (h *SessionHandler) List(c *gin.Context) {
	list, err := h.sessionSvc.List(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "failed to list sessions"})
		return
	}
	c.JSON(http.StatusOK, model.Response{Code: 0, Data: list})
}

// GetMessages handles GET /api/v1/sessions/:id/messages
func (h *SessionHandler) GetMessages(c *gin.Context) {
	sessionID := c.Param("id")
	sess, err := h.sessionSvc.Get(c.Request.Context(), sessionID)
	if err != nil {
		c.JSON(http.StatusNotFound, model.Response{Code: 40004, Message: "会话不存在"})
		return
	}
	c.JSON(http.StatusOK, model.Response{Code: 0, Data: gin.H{
		"session_id": sess.ID,
		"messages":   sess.Messages,
	}})
}

// Delete handles DELETE /api/v1/sessions/:id
func (h *SessionHandler) Delete(c *gin.Context) {
	sessionID := c.Param("id")
	if err := h.sessionSvc.Delete(c.Request.Context(), sessionID); err != nil {
		c.JSON(http.StatusNotFound, model.Response{Code: 40004, Message: "会话不存在"})
		return
	}
	c.JSON(http.StatusOK, model.Response{Code: 0, Message: "success"})
}
```

### 3. `gateway/internal/middleware/cors.go`

```go
package middleware

import (
	"github.com/gin-gonic/gin"
)

// CORS returns a middleware that handles Cross-Origin Resource Sharing.
func CORS() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", "*")
		c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Origin, Content-Type, Authorization, X-Session-ID")
		c.Header("Access-Control-Expose-Headers", "X-Session-ID")
		c.Header("Access-Control-Max-Age", "86400")

		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}

		c.Next()
	}
}
```

### 4. `gateway/internal/middleware/logging.go`

```go
package middleware

import (
	"log/slog"
	"time"

	"github.com/gin-gonic/gin"
)

// Logging returns a middleware that logs each request with structured fields.
func Logging() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path
		query := c.Request.URL.RawQuery

		c.Next()

		latency := time.Since(start)
		status := c.Writer.Status()

		slog.Info("request",
			"method", c.Request.Method,
			"path", path,
			"query", query,
			"status", status,
			"latency", latency.String(),
			"client_ip", c.ClientIP(),
		)
	}
}
```

### 5. `gateway/internal/middleware/ratelimit.go`

```go
package middleware

import (
	"net/http"
	"sync"
	"time"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/gin-gonic/gin"
)

// RateLimiter implements a simple in-memory per-IP rate limiter.
type RateLimiter struct {
	mu       sync.Mutex
	visitors map[string]*visitor
	limit    int
	window   time.Duration
}

type visitor struct {
	count    int
	resetAt  time.Time
}

// NewRateLimiter creates a rate limiter with the given limit per window.
func NewRateLimiter(limit int, window time.Duration) *RateLimiter {
	rl := &RateLimiter{
		visitors: make(map[string]*visitor),
		limit:    limit,
		window:   window,
	}
	// Cleanup expired entries every minute
	go func() {
		for {
			time.Sleep(time.Minute)
			rl.cleanup()
		}
	}()
	return rl
}

func (rl *RateLimiter) cleanup() {
	rl.mu.Lock()
	defer rl.mu.Unlock()
	now := time.Now()
	for ip, v := range rl.visitors {
		if now.After(v.resetAt) {
			delete(rl.visitors, ip)
		}
	}
}

// Middleware returns a Gin middleware that enforces rate limiting.
func (rl *RateLimiter) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		ip := c.ClientIP()

		rl.mu.Lock()
		v, exists := rl.visitors[ip]
		now := time.Now()

		if !exists || now.After(v.resetAt) {
			rl.visitors[ip] = &visitor{count: 1, resetAt: now.Add(rl.window)}
			rl.mu.Unlock()
			c.Next()
			return
		}

		v.count++
		if v.count > rl.limit {
			rl.mu.Unlock()
			c.JSON(http.StatusTooManyRequests, model.Response{
				Code:    42901,
				Message: "请求过于频繁，请稍后重试",
			})
			c.Abort()
			return
		}
		rl.mu.Unlock()

		c.Next()
	}
}
```

### 6. 更新 `gateway/cmd/server/main.go`

替换完整的路由注册和中间件配置：

```go
// Setup Gin
gin.SetMode(cfg.Server.Mode)
r := gin.New()
r.Use(gin.Recovery())
r.Use(middleware.CORS())
r.Use(middleware.Logging())

// Rate limiter: 60 requests per minute per IP
limiter := middleware.NewRateLimiter(60, time.Minute)
r.Use(limiter.Middleware())

// Handlers
healthHandler := handler.NewHealthHandler(rdb, agentClient)
chatHandler := handler.NewChatHandler(sessionSvc, agentClient)
sessionHandler := handler.NewSessionHandler(sessionSvc)
fileSvc := service.NewFileService(cfg.Upload.Dir, cfg.Upload.MaxSize)
uploadHandler := handler.NewUploadHandler(fileSvc, agentClient, cfg.GRPC.MaxRetry)

// Routes
r.GET("/health", healthHandler.Health)
r.GET("/ws", chatHandler.ChatWS)

api := r.Group("/api/v1")
{
    api.POST("/chat", chatHandler.ChatSSE)
    api.POST("/upload", uploadHandler.Upload)
    api.POST("/sessions", sessionHandler.Create)
    api.GET("/sessions", sessionHandler.List)
    api.GET("/sessions/:id/messages", sessionHandler.GetMessages)
    api.DELETE("/sessions/:id", sessionHandler.Delete)
}
```

需要添加的 import：
```go
"time"
"github.com/dkyyyy/paper-agent/gateway/internal/middleware"
```

## 验收标准

### 1. 编译检查

```bash
cd gateway
go build ./cmd/server/
```

### 2. 验收 Checklist

- [ ] `go build` 编译通过
- [ ] `GET /health` 返回 `{"status": "...", "services": {...}, "uptime": "..."}`
- [ ] Health 检查 Redis 和 Agent 连通性，任一不可用时 status 为 "degraded"
- [ ] CORS 中间件：OPTIONS 请求返回 204，响应头包含 Access-Control-Allow-Origin
- [ ] 日志中间件：每个请求打印 method, path, status, latency, client_ip
- [ ] 限流中间件：单 IP 每分钟超过 60 次返回 429
- [ ] 会话接口：POST/GET/DELETE /api/v1/sessions 正常工作
- [ ] 会话接口：GET /api/v1/sessions/:id/messages 返回消息历史
- [ ] 所有路由注册完整，main.go 编译无未使用变量

## 提交

```bash
git add gateway/
git commit -m "feat(gateway): add health check, session endpoints, and middleware

- GET /health with Redis and Agent connectivity check
- Session CRUD endpoints (create/list/messages/delete)
- CORS middleware allowing frontend access
- Structured request logging middleware
- In-memory per-IP rate limiter (60 req/min)"
```

## 注意事项

1. 限流器使用内存存储，重启后重置，当前阶段够用
2. CORS 当前允许所有来源（`*`），部署时应限制为前端域名
3. Health 检查中暂未包含 PostgreSQL（后续任务添加数据库层时补充）
