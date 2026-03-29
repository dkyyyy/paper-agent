package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"time"

	"github.com/dkyyyy/paper-agent/gateway/internal/config"
	"github.com/dkyyyy/paper-agent/gateway/internal/handler"
	"github.com/dkyyyy/paper-agent/gateway/internal/middleware"
	"github.com/dkyyyy/paper-agent/gateway/internal/service"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

func main() {
	cfgPath := "configs/config.yaml"
	if p := os.Getenv("CONFIG_PATH"); p != "" {
		cfgPath = p
	}

	cfg, err := config.Load(cfgPath)
	if err != nil {
		slog.Error("failed to load config", "error", err)
		os.Exit(1)
	}
	cfg.LogSummary()

	rdb := redis.NewClient(&redis.Options{
		Addr:     cfg.Redis.Addr,
		Password: cfg.Redis.Password,
		DB:       cfg.Redis.DB,
	})
	if err := rdb.Ping(context.Background()).Err(); err != nil {
		slog.Error("failed to connect redis", "error", err)
		os.Exit(1)
	}
	slog.Info("redis connected", "addr", cfg.Redis.Addr)
	defer rdb.Close()

	sessionSvc := service.NewSessionService(rdb)

	agentClient, err := service.NewAgentClient(cfg.GRPC.AgentAddr, cfg.GRPC.Timeout)
	if err != nil {
		slog.Error("failed to create agent client", "error", err)
		os.Exit(1)
	}
	slog.Info("agent grpc client created", "addr", cfg.GRPC.AgentAddr)
	defer agentClient.Close()

	gin.SetMode(cfg.Server.Mode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(middleware.CORS())
	r.Use(middleware.Logging())

	limiter := middleware.NewRateLimiter(60, time.Minute)
	r.Use(limiter.Middleware())

	healthHandler := handler.NewHealthHandler(rdb, agentClient)
	chatHandler := handler.NewChatHandler(sessionSvc, agentClient)
	sessionHandler := handler.NewSessionHandler(sessionSvc)
	fileSvc := service.NewFileService(cfg.Upload.Dir, cfg.Upload.MaxSize)
	uploadHandler := handler.NewUploadHandler(fileSvc, agentClient, cfg.GRPC.MaxRetry)

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

	addr := fmt.Sprintf(":%d", cfg.Server.Port)
	slog.Info("starting gateway", "addr", addr)
	if err := r.Run(addr); err != nil {
		slog.Error("server failed", "error", err)
		os.Exit(1)
	}
}
