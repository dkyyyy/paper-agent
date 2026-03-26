# Paper Agent — API 接口设计文档

## 1. Go Gateway HTTP/WebSocket 接口

### 1.1 聊天接口（WebSocket）

```
GET /ws?session_id={session_id}
Upgrade: websocket
```

**客户端发送消息格式**：
```json
{
  "type": "chat",
  "content": "调研 2023-2025 RAG 优化的最新进展",
  "attachment_ids": ["file_abc123"]
}
```

**服务端推送事件格式**：

| event | 说明 | data 字段 |
|-------|------|-----------|
| `token` | 流式文本片段 | `content`: 文本内容 |
| `agent_status` | Agent 执行状态变更 | `agent`: Agent 名称, `step`: 步骤描述 |
| `done` | 本轮对话完成 | `content`: 完整响应文本 |
| `error` | 错误 | `error`: 错误描述 |

```json
// token 事件
{"event": "token", "data": {"content": "根据检索结果，"}}

// agent_status 事件
{"event": "agent_status", "data": {"agent": "search_agent", "step": "正在检索 ArXiv..."}}

// done 事件
{"event": "done", "data": {"content": "完整的响应文本..."}}

// error 事件
{"event": "error", "data": {"error": "LLM 调用超时，请重试"}}
```

---

### 1.2 聊天接口（SSE 备选）

```
POST /api/v1/chat
Content-Type: application/json
```

**Request Body**：
```json
{
  "session_id": "uuid-string",
  "content": "调研 RAG 优化最新进展",
  "attachment_ids": ["file_abc123"]
}
```

**Response**：`Content-Type: text/event-stream`
```
event: token
data: {"content": "根据"}

event: token
data: {"content": "检索结果"}

event: agent_status
data: {"agent": "search_agent", "step": "正在检索 Semantic Scholar..."}

event: done
data: {"content": "完整响应文本..."}
```

---

### 1.3 文件上传

```
POST /api/v1/upload
Content-Type: multipart/form-data
```

**Request Fields**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话 ID |
| file | file | 是 | PDF 文件，最大 20MB |

**Response**：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "paper_id": "paper_abc123",
    "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    "page_count": 12,
    "filename": "rag_paper.pdf"
  }
}
```

**错误响应**：
```json
// 格式错误
{"code": 40001, "message": "仅支持 PDF 格式文件"}

// 文件过大
{"code": 40002, "message": "文件大小不能超过 20MB"}

// 解析失败
{"code": 50001, "message": "PDF 解析失败，请检查文件是否损坏"}
```

---

### 1.4 会话管理

**创建会话**：
```
POST /api/v1/sessions
Response: {"code": 0, "data": {"session_id": "uuid", "created_at": "2025-01-15T10:00:00Z"}}
```

**获取会话列表**：
```
GET /api/v1/sessions
Response: {
  "code": 0,
  "data": [
    {
      "session_id": "uuid",
      "created_at": "2025-01-15T10:00:00Z",
      "last_message": "调研 RAG 优化...",
      "message_count": 5
    }
  ]
}
```

**获取会话历史消息**：
```
GET /api/v1/sessions/{session_id}/messages
Response: {
  "code": 0,
  "data": {
    "session_id": "uuid",
    "messages": [
      {"role": "user", "content": "...", "timestamp": "..."},
      {"role": "assistant", "content": "...", "timestamp": "...", "metadata": {"agents_used": ["search_agent"]}}
    ]
  }
}
```

**删除会话**：
```
DELETE /api/v1/sessions/{session_id}
Response: {"code": 0, "message": "success"}
```

---

### 1.5 健康检查

```
GET /health
Response: {
  "status": "ok",
  "services": {
    "redis": "connected",
    "agent_service": "connected",
    "chroma": "connected"
  },
  "uptime": "2h30m"
}
```

---

## 2. gRPC 接口（Go ↔ Python）

### 2.1 Proto 定义

```protobuf
syntax = "proto3";
package agent.v1;

option go_package = "gateway/internal/grpc/agentpb";

service AgentService {
  // 流式对话
  rpc Chat(ChatRequest) returns (stream ChatEvent);

  // 上传论文解析
  rpc UploadPaper(UploadPaperRequest) returns (UploadPaperResponse);

  // 健康检查
  rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse);
}

// ========== Chat ==========

message ChatRequest {
  string session_id = 1;
  string content = 2;
  repeated string attachment_ids = 3;
  SessionContext context = 4;
}

message SessionContext {
  repeated ChatMessage history = 1;      // 最近 N 轮消息
  ResearchContext research = 2;          // 研究上下文
}

message ChatMessage {
  string role = 1;     // user | assistant
  string content = 2;
}

message ResearchContext {
  string topic = 1;
  repeated string analyzed_paper_ids = 2;
  string current_step = 3;
}

message ChatEvent {
  EventType event_type = 1;
  string content = 2;
  string agent_name = 3;
  string step_description = 4;
  string error_message = 5;
}

enum EventType {
  EVENT_TYPE_UNSPECIFIED = 0;
  EVENT_TYPE_TOKEN = 1;
  EVENT_TYPE_AGENT_STATUS = 2;
  EVENT_TYPE_DONE = 3;
  EVENT_TYPE_ERROR = 4;
}

// ========== Upload ==========

message UploadPaperRequest {
  string session_id = 1;
  string filename = 2;
  bytes file_content = 3;
}

message UploadPaperResponse {
  string paper_id = 1;
  string title = 2;
  int32 page_count = 3;
  bool success = 4;
  string error = 5;
}

// ========== Health ==========

message HealthCheckRequest {}

message HealthCheckResponse {
  bool healthy = 1;
  map<string, string> services = 2;
}
```

### 2.2 调用流程

```
Go Gateway                          Python Agent Service
    │                                       │
    │──── ChatRequest ─────────────────────>│
    │     (session_id, content, context)    │
    │                                       │
    │<─── ChatEvent (agent_status) ────────│  "意图识别中..."
    │<─── ChatEvent (agent_status) ────────│  "正在检索 ArXiv..."
    │<─── ChatEvent (token) ───────────────│  "根据"
    │<─── ChatEvent (token) ───────────────│  "检索结果，"
    │<─── ChatEvent (agent_status) ────────│  "正在分析论文..."
    │<─── ChatEvent (token) ───────────────│  "以下是..."
    │<─── ChatEvent (done) ────────────────│  完整文本
    │                                       │
```

### 2.3 错误处理

| gRPC Status Code | 场景 | Go 端处理 |
|------------------|------|-----------|
| UNAVAILABLE | Agent 服务不可用 | 返回 503，提示稍后重试 |
| DEADLINE_EXCEEDED | 处理超时（默认 120s） | 返回 504，提示任务超时 |
| INTERNAL | Agent 内部错误 | 返回 500，记录日志 |
| INVALID_ARGUMENT | 参数错误 | 返回 400，透传错误信息 |

---

## 3. 统一错误码

| 错误码 | 说明 | HTTP Status |
|--------|------|-------------|
| 0 | 成功 | 200 |
| 40001 | 参数校验失败 | 400 |
| 40002 | 文件格式不支持 | 400 |
| 40003 | 文件过大 | 413 |
| 40004 | 会话不存在 | 404 |
| 42901 | 请求过于频繁 | 429 |
| 50001 | 服务内部错误 | 500 |
| 50002 | Agent 服务不可用 | 503 |
| 50003 | 处理超时 | 504 |
| 50004 | LLM 调用失败 | 502 |
