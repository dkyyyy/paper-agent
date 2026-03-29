package main

import (
	"fmt"
	"log/slog"
	"os"

	"github.com/dkyyyy/paper-agent/gateway/internal/config"
	"github.com/gin-gonic/gin"
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

	gin.SetMode(cfg.Server.Mode)
	r := gin.New()
	r.Use(gin.Recovery())

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
