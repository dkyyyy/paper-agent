# Codex 执行指令 — 任务 2.3：gRPC 客户端封装

## 任务目标

封装 Python Agent Service 的 gRPC 客户端，支持流式接收 ChatEvent，带超时和重试机制。

## 前置依赖

- 任务 1.1 已完成（Proto 定义 + Go 生成代码）
- 任务 2.1 已完成（Go 项目初始化、配置管理）
- gRPC 生成代码在 `gateway/internal/grpc/agentpb/`

## 需要创建的文件

### 1. `gateway/internal/service/agent_client.go`

```go
package service

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"time"

	pb "github.com/dkyyyy/paper-agent/gateway/internal/grpc/agentpb"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// AgentClient wraps the gRPC connection to the Python Agent Service.
type AgentClient struct {
	conn    *grpc.ClientConn
	client  pb.AgentServiceClient
	timeout time.Duration
}

// NewAgentClient creates a gRPC client connected to the agent service.
func NewAgentClient(addr string, timeout time.Duration) (*AgentClient, error) {
	conn, err := grpc.NewClient(addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		return nil, fmt.Errorf("grpc dial %s: %w", addr, err)
	}

	return &AgentClient{
		conn:    conn,
		client:  pb.NewAgentServiceClient(conn),
		timeout: timeout,
	}, nil
}

// ChatEvent represents a single event from the agent stream.
type ChatEvent struct {
	EventType       string // token | agent_status | done | error
	Content         string
	AgentName       string
	StepDescription string
	ErrorMessage    string
}

// Chat sends a message and returns a channel of streaming events.
// The channel is closed when the stream ends or an error occurs.
// Cancel the context to stop receiving events.
func (c *AgentClient) Chat(ctx context.Context, req *pb.ChatRequest) (<-chan ChatEvent, <-chan error) {
	eventCh := make(chan ChatEvent, 32)
	errCh := make(chan error, 1)

	go func() {
		defer close(eventCh)
		defer close(errCh)

		ctx, cancel := context.WithTimeout(ctx, c.timeout)
		defer cancel()

		stream, err := c.client.Chat(ctx, req)
		if err != nil {
			errCh <- fmt.Errorf("start chat stream: %w", err)
			return
		}

		for {
			event, err := stream.Recv()
			if err == io.EOF {
				return
			}
			if err != nil {
				errCh <- fmt.Errorf("recv chat event: %w", err)
				return
			}

			eventCh <- ChatEvent{
				EventType:       eventTypeToString(event.EventType),
				Content:         event.Content,
				AgentName:       event.AgentName,
				StepDescription: event.StepDescription,
				ErrorMessage:    event.ErrorMessage,
			}
		}
	}()

	return eventCh, errCh
}

// UploadPaper sends a file to the agent service for parsing.
// Retries up to maxRetry times on transient failures.
func (c *AgentClient) UploadPaper(ctx context.Context, req *pb.UploadPaperRequest, maxRetry int) (*pb.UploadPaperResponse, error) {
	var lastErr error
	for i := 0; i <= maxRetry; i++ {
		if i > 0 {
			backoff := time.Duration(1<<uint(i-1)) * time.Second
			slog.Warn("retrying UploadPaper", "attempt", i+1, "backoff", backoff)
			time.Sleep(backoff)
		}

		ctx, cancel := context.WithTimeout(ctx, c.timeout)
		resp, err := c.client.UploadPaper(ctx, req)
		cancel()

		if err == nil {
			return resp, nil
		}
		lastErr = err
	}
	return nil, fmt.Errorf("upload paper after %d retries: %w", maxRetry+1, lastErr)
}

// HealthCheck checks if the agent service is healthy.
func (c *AgentClient) HealthCheck(ctx context.Context) (*pb.HealthCheckResponse, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	return c.client.HealthCheck(ctx, &pb.HealthCheckRequest{})
}

// Close closes the gRPC connection.
func (c *AgentClient) Close() error {
	return c.conn.Close()
}

func eventTypeToString(t pb.EventType) string {
	switch t {
	case pb.EventType_EVENT_TYPE_TOKEN:
		return "token"
	case pb.EventType_EVENT_TYPE_AGENT_STATUS:
		return "agent_status"
	case pb.EventType_EVENT_TYPE_DONE:
		return "done"
	case pb.EventType_EVENT_TYPE_ERROR:
		return "error"
	default:
		return "unknown"
	}
}
```

### 2. 更新 `gateway/cmd/server/main.go`

在 Redis 初始化之后添加 gRPC 客户端初始化：

```go
// Init Agent gRPC client
agentClient, err := service.NewAgentClient(cfg.GRPC.AgentAddr, cfg.GRPC.Timeout)
if err != nil {
    slog.Error("failed to create agent client", "error", err)
    os.Exit(1)
}
slog.Info("agent grpc client created", "addr", cfg.GRPC.AgentAddr)
defer agentClient.Close()
```

## 验收标准

### 1. 编译检查

```bash
cd gateway
go build ./cmd/server/
```

预期：编译通过。

### 2. 验收 Checklist

- [ ] `go build` 编译通过
- [ ] `NewAgentClient` 接受地址和超时参数，创建 gRPC 连接
- [ ] `Chat` 方法返回 event channel 和 error channel，支持流式接收
- [ ] `Chat` 支持 context 取消（用户断开时停止接收）
- [ ] `Chat` 有超时控制（使用配置中的 timeout）
- [ ] `UploadPaper` 支持重试（指数退避，最多 maxRetry 次）
- [ ] `HealthCheck` 有独立的 5s 超时
- [ ] `Close` 正确关闭 gRPC 连接
- [ ] main.go 中正确初始化 AgentClient

## 提交

```bash
git add gateway/internal/service/agent_client.go gateway/cmd/
git commit -m "feat(gateway): implement gRPC agent client with streaming and retry

- Add AgentClient wrapping gRPC connection to Python agent service
- Chat method returns channels for async streaming event consumption
- UploadPaper with exponential backoff retry (configurable max retry)
- HealthCheck with 5s timeout
- Context cancellation support for all RPCs"
```

## 注意事项

1. Chat 使用 channel 模式而非回调，方便后续 WebSocket/SSE 转发
2. 当前不需要连接池，单连接 gRPC 内部已做多路复用
3. 不要在此任务中测试实际连接（Python 服务还没实现），编译通过即可
