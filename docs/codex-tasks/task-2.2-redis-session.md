# Codex 执行指令 — 任务 2.2：Redis 会话管理

## 任务目标

实现基于 Redis 的会话 CRUD，包括创建会话、获取会话、追加消息、删除会话、列出会话。

## 前置依赖

- 任务 2.1 已完成（Go 项目初始化、配置管理）
- Redis 配置已在 `gateway/configs/config.yaml` 中定义
- 参考文档：`docs/04-api-design.md` 会话管理接口

## 需要创建的文件

### 1. `gateway/internal/model/session.go`

```go
package model

import "time"

type Session struct {
	ID           string    `json:"session_id"`
	Title        string    `json:"title"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
	Messages     []Message `json:"messages"`
	MessageCount int       `json:"message_count"`
}

type SessionSummary struct {
	ID           string    `json:"session_id"`
	Title        string    `json:"title"`
	CreatedAt    time.Time `json:"created_at"`
	LastMessage  string    `json:"last_message"`
	MessageCount int       `json:"message_count"`
}

type Message struct {
	Role      string                 `json:"role"`      // user | assistant
	Content   string                 `json:"content"`
	Metadata  map[string]interface{} `json:"metadata,omitempty"`
	Timestamp time.Time              `json:"timestamp"`
}
```

### 2. `gateway/internal/service/session.go`

```go
package service

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

const (
	sessionKeyPrefix = "session:"
	sessionTTL       = 1 * time.Hour
)

type SessionService interface {
	Create(ctx context.Context) (*model.Session, error)
	Get(ctx context.Context, sessionID string) (*model.Session, error)
	AppendMessage(ctx context.Context, sessionID string, msg model.Message) error
	Delete(ctx context.Context, sessionID string) error
	List(ctx context.Context) ([]*model.SessionSummary, error)
}

type sessionService struct {
	rdb *redis.Client
}

func NewSessionService(rdb *redis.Client) SessionService {
	return &sessionService{rdb: rdb}
}

func sessionKey(id string) string {
	return sessionKeyPrefix + id
}

func (s *sessionService) Create(ctx context.Context) (*model.Session, error) {
	sess := &model.Session{
		ID:        uuid.New().String(),
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
		Messages:  []model.Message{},
	}

	data, err := json.Marshal(sess)
	if err != nil {
		return nil, fmt.Errorf("marshal session: %w", err)
	}

	if err := s.rdb.Set(ctx, sessionKey(sess.ID), data, sessionTTL).Err(); err != nil {
		return nil, fmt.Errorf("redis set: %w", err)
	}

	return sess, nil
}

func (s *sessionService) Get(ctx context.Context, sessionID string) (*model.Session, error) {
	data, err := s.rdb.Get(ctx, sessionKey(sessionID)).Bytes()
	if err == redis.Nil {
		return nil, fmt.Errorf("session not found: %s", sessionID)
	}
	if err != nil {
		return nil, fmt.Errorf("redis get: %w", err)
	}

	var sess model.Session
	if err := json.Unmarshal(data, &sess); err != nil {
		return nil, fmt.Errorf("unmarshal session: %w", err)
	}

	return &sess, nil
}

func (s *sessionService) AppendMessage(ctx context.Context, sessionID string, msg model.Message) error {
	sess, err := s.Get(ctx, sessionID)
	if err != nil {
		return err
	}

	msg.Timestamp = time.Now()
	sess.Messages = append(sess.Messages, msg)
	sess.MessageCount = len(sess.Messages)
	sess.UpdatedAt = time.Now()

	// Auto-generate title from first user message
	if sess.Title == "" && msg.Role == "user" {
		title := msg.Content
		if len(title) > 50 {
			title = title[:50] + "..."
		}
		sess.Title = title
	}

	data, err := json.Marshal(sess)
	if err != nil {
		return fmt.Errorf("marshal session: %w", err)
	}

	if err := s.rdb.Set(ctx, sessionKey(sessionID), data, sessionTTL).Err(); err != nil {
		return fmt.Errorf("redis set: %w", err)
	}

	return nil
}

func (s *sessionService) Delete(ctx context.Context, sessionID string) error {
	result, err := s.rdb.Del(ctx, sessionKey(sessionID)).Result()
	if err != nil {
		return fmt.Errorf("redis del: %w", err)
	}
	if result == 0 {
		return fmt.Errorf("session not found: %s", sessionID)
	}
	return nil
}

func (s *sessionService) List(ctx context.Context) ([]*model.SessionSummary, error) {
	keys, err := s.rdb.Keys(ctx, sessionKeyPrefix+"*").Result()
	if err != nil {
		return nil, fmt.Errorf("redis keys: %w", err)
	}

	summaries := make([]*model.SessionSummary, 0, len(keys))
	for _, key := range keys {
		data, err := s.rdb.Get(ctx, key).Bytes()
		if err != nil {
			continue // skip expired keys
		}

		var sess model.Session
		if err := json.Unmarshal(data, &sess); err != nil {
			continue
		}

		summary := &model.SessionSummary{
			ID:           sess.ID,
			Title:        sess.Title,
			CreatedAt:    sess.CreatedAt,
			MessageCount: len(sess.Messages),
		}
		if len(sess.Messages) > 0 {
			last := sess.Messages[len(sess.Messages)-1]
			summary.LastMessage = last.Content
			if len(summary.LastMessage) > 100 {
				summary.LastMessage = summary.LastMessage[:100] + "..."
			}
		}
		summaries = append(summaries, summary)
	}

	return summaries, nil
}
```

### 3. `gateway/internal/service/session_test.go`

```go
package service

import (
	"context"
	"testing"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/redis/go-redis/v9"
)

// 需要本地 Redis 运行在 localhost:6379
func newTestRedis() *redis.Client {
	return redis.NewClient(&redis.Options{
		Addr: "localhost:6379",
		DB:   15, // 使用 DB 15 做测试，避免污染
	})
}

func TestSessionCRUD(t *testing.T) {
	rdb := newTestRedis()
	ctx := context.Background()
	defer rdb.FlushDB(ctx)

	svc := NewSessionService(rdb)

	// Create
	sess, err := svc.Create(ctx)
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}
	if sess.ID == "" {
		t.Fatal("session ID should not be empty")
	}

	// Get
	got, err := svc.Get(ctx, sess.ID)
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}
	if got.ID != sess.ID {
		t.Fatalf("expected ID %s, got %s", sess.ID, got.ID)
	}

	// AppendMessage
	err = svc.AppendMessage(ctx, sess.ID, model.Message{
		Role:    "user",
		Content: "调研 RAG 优化最新进展",
	})
	if err != nil {
		t.Fatalf("AppendMessage failed: %v", err)
	}

	got, _ = svc.Get(ctx, sess.ID)
	if len(got.Messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(got.Messages))
	}
	if got.Title == "" {
		t.Fatal("title should be auto-generated from first user message")
	}

	// List
	list, err := svc.List(ctx)
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}
	if len(list) < 1 {
		t.Fatal("expected at least 1 session in list")
	}

	// Delete
	err = svc.Delete(ctx, sess.ID)
	if err != nil {
		t.Fatalf("Delete failed: %v", err)
	}

	_, err = svc.Get(ctx, sess.ID)
	if err == nil {
		t.Fatal("expected error after delete, got nil")
	}
}
```

### 4. 更新 `gateway/cmd/server/main.go`

在现有 main.go 中添加 Redis 连接初始化（在 config 加载之后、Gin 启动之前）：

```go
// 在 cfg.LogSummary() 之后添加：

// Init Redis
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

// Init services
sessionSvc := service.NewSessionService(rdb)
_ = sessionSvc // 后续任务中注入到 handler
```

需要添加的 import：
```go
"context"
"github.com/dkyyyy/paper-agent/gateway/internal/service"
"github.com/redis/go-redis/v9"
```

## 验收标准

### 1. 编译检查

```bash
cd gateway
go build ./cmd/server/
```

### 2. 单元测试（需要本地 Redis）

```bash
cd gateway
go test ./internal/service/ -v -run TestSessionCRUD
```

预期：所有测试通过。

### 3. 验收 Checklist

- [ ] `go build` 编译通过
- [ ] 创建会话返回 UUID，Redis 中可查到对应 key（`session:{uuid}`）
- [ ] 会话 1 小时后自动过期（TTL）
- [ ] AppendMessage 正确追加消息到会话历史
- [ ] 首条用户消息自动生成会话标题（截取前 50 字符）
- [ ] List 返回所有未过期会话的摘要（ID + 创建时间 + 最后消息预览）
- [ ] Delete 删除后 Get 返回 not found 错误
- [ ] 单元测试全部通过

## 提交

```bash
git add gateway/internal/model/ gateway/internal/service/ gateway/cmd/
git commit -m "feat(gateway): implement Redis session management

- Add Session and Message data models
- Implement SessionService with Create/Get/AppendMessage/Delete/List
- Auto-generate session title from first user message
- Session TTL 1 hour with Redis expiration
- Add unit tests for session CRUD operations"
```

## 注意事项

1. 安装新依赖：`go get github.com/google/uuid`
2. 测试使用 Redis DB 15，避免污染开发数据
3. `List` 使用 `KEYS` 命令，生产环境数据量大时应改为 `SCAN`，当前阶段够用
4. 后续任务 2.2 会将 session 持久化到 PostgreSQL，Redis 仅作为热缓存
