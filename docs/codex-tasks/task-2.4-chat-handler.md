# Codex 执行指令 — 任务 2.4：HTTP 聊天接口

## 任务目标

实现 `POST /api/v1/chat`（SSE 流式响应）和 `GET /ws`（WebSocket）聊天接口。

## 前置依赖

- 任务 2.1（配置管理）、2.2（会话管理）、2.3（gRPC 客户端）已完成
- 参考文档：`docs/04-api-design.md` 聊天接口定义

## 需要创建的文件

### 1. `gateway/internal/model/chat.go`

```go
package model

// ChatRequest is the HTTP request body for chat.
type ChatRequest struct {
	SessionID     string   `json:"session_id"`
	Content       string   `json:"content" binding:"required"`
	AttachmentIDs []string `json:"attachment_ids"`
}

// Response is the unified HTTP response wrapper.
type Response struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

// WSMessage is the WebSocket incoming message format.
type WSMessage struct {
	Type          string   `json:"type"`    // chat
	Content       string   `json:"content"`
	AttachmentIDs []string `json:"attachment_ids"`
}

// StreamEvent is the WebSocket/SSE outgoing event format.
type StreamEvent struct {
	Event string      `json:"event"` // token | agent_status | done | error
	Data  interface{} `json:"data"`
}

// StreamTokenData is the data payload for token events.
type StreamTokenData struct {
	Content string `json:"content"`
}

// StreamAgentStatusData is the data payload for agent_status events.
type StreamAgentStatusData struct {
	Agent string `json:"agent"`
	Step  string `json:"step"`
}

// StreamErrorData is the data payload for error events.
type StreamErrorData struct {
	Error string `json:"error"`
}
```

### 2. `gateway/internal/handler/chat.go`

```go
package handler

import (
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"

	"github.com/dkyyyy/paper-agent/gateway/internal/grpc/agentpb"
	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/dkyyyy/paper-agent/gateway/internal/service"
	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
)

type ChatHandler struct {
	sessionSvc  service.SessionService
	agentClient *service.AgentClient
}

func NewChatHandler(sessionSvc service.SessionService, agentClient *service.AgentClient) *ChatHandler {
	return &ChatHandler{
		sessionSvc:  sessionSvc,
		agentClient: agentClient,
	}
}

// ChatSSE handles POST /api/v1/chat with Server-Sent Events response.
func (h *ChatHandler) ChatSSE(c *gin.Context) {
	var req model.ChatRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, model.Response{Code: 40001, Message: "content is required"})
		return
	}

	// Auto-create session if not provided
	if req.SessionID == "" {
		sess, err := h.sessionSvc.Create(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "failed to create session"})
			return
		}
		req.SessionID = sess.ID
	}

	// Save user message
	h.sessionSvc.AppendMessage(c.Request.Context(), req.SessionID, model.Message{
		Role:    "user",
		Content: req.Content,
	})

	// Build gRPC request
	grpcReq := &agentpb.ChatRequest{
		SessionId:     req.SessionID,
		Content:       req.Content,
		AttachmentIds: req.AttachmentIDs,
	}

	// Start streaming
	eventCh, errCh := h.agentClient.Chat(c.Request.Context(), grpcReq)

	// Set SSE headers
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Session-ID", req.SessionID)

	fullContent := ""
	c.Stream(func(w io.Writer) bool {
		select {
		case event, ok := <-eventCh:
			if !ok {
				return false
			}
			var data interface{}
			switch event.EventType {
			case "token":
				fullContent += event.Content
				data = model.StreamTokenData{Content: event.Content}
			case "agent_status":
				data = model.StreamAgentStatusData{Agent: event.AgentName, Step: event.StepDescription}
			case "done":
				fullContent = event.Content
				data = model.StreamTokenData{Content: event.Content}
			case "error":
				data = model.StreamErrorData{Error: event.ErrorMessage}
			}

			jsonData, _ := json.Marshal(model.StreamEvent{Event: event.EventType, Data: data})
			fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event.EventType, jsonData)
			return true

		case err, ok := <-errCh:
			if !ok {
				return false
			}
			slog.Error("agent stream error", "error", err)
			jsonData, _ := json.Marshal(model.StreamEvent{Event: "error", Data: model.StreamErrorData{Error: err.Error()}})
			fmt.Fprintf(w, "event: error\ndata: %s\n\n", jsonData)
			return false

		case <-c.Request.Context().Done():
			return false
		}
	})

	// Save assistant message
	if fullContent != "" {
		h.sessionSvc.AppendMessage(c.Request.Context(), req.SessionID, model.Message{
			Role:    "assistant",
			Content: fullContent,
		})
	}
}

// WebSocket upgrader
var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

// ChatWS handles GET /ws?session_id=xxx WebSocket connection.
func (h *ChatHandler) ChatWS(c *gin.Context) {
	sessionID := c.Query("session_id")

	// Auto-create session if not provided
	if sessionID == "" {
		sess, err := h.sessionSvc.Create(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "failed to create session"})
			return
		}
		sessionID = sess.ID
	}

	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		slog.Error("websocket upgrade failed", "error", err)
		return
	}
	defer conn.Close()

	// Send session_id to client
	conn.WriteJSON(model.StreamEvent{Event: "session", Data: map[string]string{"session_id": sessionID}})

	for {
		// Read message from client
		_, msgBytes, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				slog.Error("websocket read error", "error", err)
			}
			return
		}

		var wsMsg model.WSMessage
		if err := json.Unmarshal(msgBytes, &wsMsg); err != nil {
			conn.WriteJSON(model.StreamEvent{Event: "error", Data: model.StreamErrorData{Error: "invalid message format"}})
			continue
		}

		if wsMsg.Content == "" {
			conn.WriteJSON(model.StreamEvent{Event: "error", Data: model.StreamErrorData{Error: "content is required"}})
			continue
		}

		// Save user message
		h.sessionSvc.AppendMessage(c.Request.Context(), sessionID, model.Message{
			Role:    "user",
			Content: wsMsg.Content,
		})

		// Build gRPC request
		grpcReq := &agentpb.ChatRequest{
			SessionId:     sessionID,
			Content:       wsMsg.Content,
			AttachmentIds: wsMsg.AttachmentIDs,
		}

		// Stream events to WebSocket
		eventCh, errCh := h.agentClient.Chat(c.Request.Context(), grpcReq)
		fullContent := ""

		streaming := true
		for streaming {
			select {
			case event, ok := <-eventCh:
				if !ok {
					streaming = false
					break
				}
				var data interface{}
				switch event.EventType {
				case "token":
					fullContent += event.Content
					data = model.StreamTokenData{Content: event.Content}
				case "agent_status":
					data = model.StreamAgentStatusData{Agent: event.AgentName, Step: event.StepDescription}
				case "done":
					fullContent = event.Content
					data = model.StreamTokenData{Content: event.Content}
				case "error":
					data = model.StreamErrorData{Error: event.ErrorMessage}
				}
				conn.WriteJSON(model.StreamEvent{Event: event.EventType, Data: data})

			case err, ok := <-errCh:
				if ok {
					slog.Error("agent stream error", "error", err)
					conn.WriteJSON(model.StreamEvent{Event: "error", Data: model.StreamErrorData{Error: err.Error()}})
				}
				streaming = false
			}
		}

		// Save assistant message
		if fullContent != "" {
			h.sessionSvc.AppendMessage(c.Request.Context(), sessionID, model.Message{
				Role:    "assistant",
				Content: fullContent,
			})
		}
	}
}
```

### 3. 更新 `gateway/cmd/server/main.go`

替换路由注册部分：

```go
// 在 sessionSvc 和 agentClient 初始化之后添加：

chatHandler := handler.NewChatHandler(sessionSvc, agentClient)

// Routes
api := r.Group("/api/v1")
{
    api.POST("/chat", chatHandler.ChatSSE)
}
r.GET("/ws", chatHandler.ChatWS)
```

需要添加的 import：
```go
"github.com/dkyyyy/paper-agent/gateway/internal/handler"
```

需要安装的依赖：
```bash
go get github.com/gorilla/websocket
```

## 验收标准

### 1. 编译检查

```bash
cd gateway
go build ./cmd/server/
```

### 2. 验收 Checklist

- [ ] `go build` 编译通过
- [ ] SSE 接口：`POST /api/v1/chat` 设置正确的 SSE headers（Content-Type: text/event-stream）
- [ ] SSE 接口：无 session_id 时自动创建新会话
- [ ] SSE 接口：content 为空时返回 400 错误
- [ ] SSE 接口：响应头包含 X-Session-ID
- [ ] WebSocket 接口：`GET /ws` 成功升级连接
- [ ] WebSocket 接口：连接后立即发送 session_id 事件
- [ ] WebSocket 接口：无 session_id 参数时自动创建
- [ ] WebSocket 接口：消息格式错误时返回 error 事件（不断开连接）
- [ ] 两种接口都正确保存用户消息和助手消息到会话
- [ ] 两种接口都支持 context 取消（客户端断开时停止 gRPC 流）

## 提交

```bash
git add gateway/
git commit -m "feat(gateway): implement SSE and WebSocket chat endpoints

- POST /api/v1/chat with Server-Sent Events streaming
- GET /ws with WebSocket bidirectional streaming
- Auto-create session when session_id not provided
- Save user and assistant messages to session
- Forward gRPC agent events to client in real-time
- Add chat request/response models"
```

## 注意事项

1. 安装 `gorilla/websocket`：`go get github.com/gorilla/websocket`
2. WebSocket upgrader 的 CheckOrigin 当前允许所有来源，生产环境需限制
3. 当前无法端到端测试（Python Agent 未实现），编译通过 + 代码审查即可
4. SSE 和 WebSocket 共用同一套 gRPC 调用逻辑和消息保存逻辑
