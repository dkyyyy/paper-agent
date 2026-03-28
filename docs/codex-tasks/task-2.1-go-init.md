# Codex 执行指令 — 任务 2.1：Go 项目初始化与配置管理

## 任务目标

初始化 Go 项目，实现 YAML 配置加载（Viper），包含所有服务连接配置。

## 前置上下文

- 项目根目录：`paper-agent/`
- Go 代码在 `gateway/` 子目录
- gRPC Proto 已生成在 `gateway/internal/grpc/agentpb/`
- 参考文档：`docs/01-architecture.md`、`docs/02-dev-standards.md`

## 需要创建的文件

### 1. `gateway/go.mod`

```
module github.com/dkyyyy/paper-agent/gateway

go 1.22
```

初始化后安装依赖：
```bash
cd gateway
go mod init github.com/dkyyyy/paper-agent/gateway
go get github.com/gin-gonic/gin
go get github.com/spf13/viper
go get github.com/redis/go-redis/v9
go get google.golang.org/grpc
go get google.golang.org/protobuf
```

### 2. `gateway/configs/config.yaml`

```yaml
server:
  port: 8080
  mode: debug  # debug | release

redis:
  addr: localhost:6379
  password: ""
  db: 0

grpc:
  agent_addr: localhost:50051
  timeout: 120s       # Agent 处理超时
  max_retry: 3

postgres:
  host: localhost
  port: 5432
  user: paper_agent
  password: paper_agent
  dbname: paper_agent
  sslmode: disable

upload:
  max_size: 20971520  # 20MB
  dir: ./uploads

log:
  level: info         # debug | info | warn | error
```

### 3. `gateway/internal/config/config.go`

实现配置结构体和加载逻辑：

```go
package config

import (
	"fmt"
	"log/slog"
	"time"

	"github.com/spf13/viper"
)

type Config struct {
	Server   ServerConfig   `mapstructure:"server"`
	Redis    RedisConfig    `mapstructure:"redis"`
	GRPC     GRPCConfig     `mapstructure:"grpc"`
	Postgres PostgresConfig `mapstructure:"postgres"`
	Upload   UploadConfig   `mapstructure:"upload"`
	Log      LogConfig      `mapstructure:"log"`
}

type ServerConfig struct {
	Port int    `mapstructure:"port"`
	Mode string `mapstructure:"mode"`
}

type RedisConfig struct {
	Addr     string `mapstructure:"addr"`
	Password string `mapstructure:"password"`
	DB       int    `mapstructure:"db"`
}

type GRPCConfig struct {
	AgentAddr string        `mapstructure:"agent_addr"`
	Timeout   time.Duration `mapstructure:"timeout"`
	MaxRetry  int           `mapstructure:"max_retry"`
}

type PostgresConfig struct {
	Host     string `mapstructure:"host"`
	Port     int    `mapstructure:"port"`
	User     string `mapstructure:"user"`
	Password string `mapstructure:"password"`
	DBName   string `mapstructure:"dbname"`
	SSLMode  string `mapstructure:"sslmode"`
}

func (p *PostgresConfig) DSN() string {
	return fmt.Sprintf("host=%s port=%d user=%s password=%s dbname=%s sslmode=%s",
		p.Host, p.Port, p.User, p.Password, p.DBName, p.SSLMode)
}

type UploadConfig struct {
	MaxSize int64  `mapstructure:"max_size"`
	Dir     string `mapstructure:"dir"`
}

type LogConfig struct {
	Level string `mapstructure:"level"`
}

// Load reads config from file and environment variables.
// Environment variables override file values, e.g. REDIS_ADDR overrides redis.addr.
func Load(path string) (*Config, error) {
	v := viper.New()
	v.SetConfigFile(path)
	v.AutomaticEnv()

	// Map env vars: REDIS_ADDR -> redis.addr, GRPC_AGENT_ADDR -> grpc.agent_addr, etc.
	v.SetEnvPrefix("")
	v.BindEnv("redis.addr", "REDIS_ADDR")
	v.BindEnv("redis.password", "REDIS_PASSWORD")
	v.BindEnv("grpc.agent_addr", "GRPC_AGENT_ADDR")
	v.BindEnv("postgres.host", "POSTGRES_HOST")
	v.BindEnv("postgres.port", "POSTGRES_PORT")
	v.BindEnv("postgres.user", "POSTGRES_USER")
	v.BindEnv("postgres.password", "POSTGRES_PASSWORD")
	v.BindEnv("postgres.dbname", "POSTGRES_DBNAME")
	v.BindEnv("server.port", "GATEWAY_PORT")

	if err := v.ReadInConfig(); err != nil {
		return nil, fmt.Errorf("read config: %w", err)
	}

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("unmarshal config: %w", err)
	}

	return &cfg, nil
}

// LogSummary prints a sanitized config summary (passwords masked).
func (c *Config) LogSummary() {
	slog.Info("config loaded",
		"server_port", c.Server.Port,
		"server_mode", c.Server.Mode,
		"redis_addr", c.Redis.Addr,
		"grpc_agent_addr", c.GRPC.AgentAddr,
		"grpc_timeout", c.GRPC.Timeout,
		"postgres_host", c.Postgres.Host,
		"postgres_port", c.Postgres.Port,
		"postgres_dbname", c.Postgres.DBName,
		"upload_max_size", c.Upload.MaxSize,
		"upload_dir", c.Upload.Dir,
		"log_level", c.Log.Level,
	)
}
```

### 4. `gateway/cmd/server/main.go`

最小入口，加载配置并启动 Gin：

```go
package main

import (
	"fmt"
	"log/slog"
	"os"

	"github.com/dkyyyy/paper-agent/gateway/internal/config"
	"github.com/gin-gonic/gin"
)

func main() {
	// Load config
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

	// Setup Gin
	gin.SetMode(cfg.Server.Mode)
	r := gin.New()
	r.Use(gin.Recovery())

	// Health check
	r.GET("/health", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok"})
	})

	// Start server
	addr := fmt.Sprintf(":%d", cfg.Server.Port)
	slog.Info("starting gateway", "addr", addr)
	if err := r.Run(addr); err != nil {
		slog.Error("server failed", "error", err)
		os.Exit(1)
	}
}
```

## 验收标准

### 1. 编译检查

```bash
cd gateway
go build ./cmd/server/
```

预期：编译成功，无报错。

### 2. 运行检查

```bash
cd gateway
go run ./cmd/server/
```

预期：
- 控制台输出配置摘要日志（不含密码明文）
- 服务在 :8080 端口启动
- `curl http://localhost:8080/health` 返回 `{"status":"ok"}`

### 3. 环境变量覆盖检查

```bash
GATEWAY_PORT=9090 go run ./cmd/server/
```

预期：服务在 :9090 端口启动。

### 4. 验收 Checklist

- [ ] `go build` 编译通过
- [ ] 配置文件加载正确（YAML 所有字段映射到结构体）
- [ ] 环境变量可覆盖配置文件值
- [ ] 启动时打印配置摘要日志（密码不输出）
- [ ] `/health` 端点返回 200
- [ ] 项目结构符合 `docs/01-architecture.md` 中 gateway 目录约定

## 提交

```bash
git add gateway/
git commit -m "feat(gateway): init Go project with config management

- Initialize Go module with Gin, Viper, go-redis, gRPC dependencies
- Implement YAML config loading with env var override
- Add server entry point with health check endpoint
- Add config.yaml with all service connection settings"
```

## 注意事项

1. `go.mod` 的 module 路径必须是 `github.com/dkyyyy/paper-agent/gateway`
2. 不要在 main.go 中初始化 Redis/gRPC 连接，这些在后续任务中实现
3. `configs/config.yaml` 中的密码是开发默认值，生产环境通过环境变量覆盖
