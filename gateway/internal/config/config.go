package config

import (
	"fmt"
	"log/slog"
	"time"

	"github.com/spf13/viper"
)

// Config groups all gateway runtime configuration.
type Config struct {
	Server   ServerConfig   `mapstructure:"server"`
	Redis    RedisConfig    `mapstructure:"redis"`
	GRPC     GRPCConfig     `mapstructure:"grpc"`
	Postgres PostgresConfig `mapstructure:"postgres"`
	Upload   UploadConfig   `mapstructure:"upload"`
	Log      LogConfig      `mapstructure:"log"`
}

// ServerConfig defines HTTP server settings.
type ServerConfig struct {
	Port int    `mapstructure:"port"`
	Mode string `mapstructure:"mode"`
}

// RedisConfig defines Redis connection settings.
type RedisConfig struct {
	Addr     string `mapstructure:"addr"`
	Password string `mapstructure:"password"`
	DB       int    `mapstructure:"db"`
}

// GRPCConfig defines Python agent gRPC settings.
type GRPCConfig struct {
	AgentAddr string        `mapstructure:"agent_addr"`
	Timeout   time.Duration `mapstructure:"timeout"`
	MaxRetry  int           `mapstructure:"max_retry"`
}

// PostgresConfig defines PostgreSQL connection settings.
type PostgresConfig struct {
	Host     string `mapstructure:"host"`
	Port     int    `mapstructure:"port"`
	User     string `mapstructure:"user"`
	Password string `mapstructure:"password"`
	DBName   string `mapstructure:"dbname"`
	SSLMode  string `mapstructure:"sslmode"`
}

// DSN returns the PostgreSQL DSN string.
func (p *PostgresConfig) DSN() string {
	return fmt.Sprintf("host=%s port=%d user=%s password=%s dbname=%s sslmode=%s",
		p.Host, p.Port, p.User, p.Password, p.DBName, p.SSLMode)
}

// UploadConfig defines upload settings.
type UploadConfig struct {
	MaxSize int64  `mapstructure:"max_size"`
	Dir     string `mapstructure:"dir"`
}

// LogConfig defines logging settings.
type LogConfig struct {
	Level string `mapstructure:"level"`
}

// Load reads config from file and environment variables.
func Load(path string) (*Config, error) {
	v := viper.New()
	v.SetConfigFile(path)
	v.AutomaticEnv()
	v.SetEnvPrefix("")

	for _, binding := range []struct {
		key string
		env string
	}{
		{key: "redis.addr", env: "REDIS_ADDR"},
		{key: "redis.password", env: "REDIS_PASSWORD"},
		{key: "grpc.agent_addr", env: "GRPC_AGENT_ADDR"},
		{key: "postgres.host", env: "POSTGRES_HOST"},
		{key: "postgres.port", env: "POSTGRES_PORT"},
		{key: "postgres.user", env: "POSTGRES_USER"},
		{key: "postgres.password", env: "POSTGRES_PASSWORD"},
		{key: "postgres.dbname", env: "POSTGRES_DBNAME"},
		{key: "server.port", env: "GATEWAY_PORT"},
	} {
		if err := v.BindEnv(binding.key, binding.env); err != nil {
			return nil, fmt.Errorf("bind env %s: %w", binding.env, err)
		}
	}

	if err := v.ReadInConfig(); err != nil {
		return nil, fmt.Errorf("read config: %w", err)
	}

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("unmarshal config: %w", err)
	}

	return &cfg, nil
}

// LogSummary prints a sanitized config summary.
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
