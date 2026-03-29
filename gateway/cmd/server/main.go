package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"

	"github.com/dkyyyy/paper-agent/gateway/internal/config"
	"github.com/dkyyyy/paper-agent/gateway/internal/handler"
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

	chatHandler := handler.NewChatHandler(sessionSvc, agentClient)

	api := r.Group("/api/v1")
	{
		api.POST("/chat", chatHandler.ChatSSE)
	}
	r.GET("/ws", chatHandler.ChatWS)
	r.GET("/health", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok"})
	})

	addr := fmt.Sprintf(":%d", cfg.Server.Port)
	slog.Info("starting gateway", "addr", addr)
	if err := r.Run(addr); err != nil {
		slog.Error("server failed", "error", err)
		os.Exit(1)
	}
}
