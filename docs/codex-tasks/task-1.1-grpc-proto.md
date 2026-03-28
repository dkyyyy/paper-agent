# Codex 执行指令 — 任务 1.1：定义 Agent 服务 Proto

## 任务目标

定义 Go Gateway 与 Python Agent Service 之间的 gRPC 通信接口。

## 文件路径

`proto/agent/v1/agent.proto`

## 前置准备

创建目录结构：
```bash
mkdir -p proto/agent/v1
```

## Proto 文件内容

创建 `proto/agent/v1/agent.proto`，内容如下：

```protobuf
syntax = "proto3";

package agent.v1;

option go_package = "github.com/dkyyyy/paper-agent/gateway/internal/grpc/agentpb";

// Agent 服务：Go Gateway 调用 Python Agent Service
service AgentService {
  // 流式对话：客户端发送一条消息，服务端流式返回多个事件
  rpc Chat(ChatRequest) returns (stream ChatEvent);

  // 上传论文：传入文件内容，返回解析结果
  rpc UploadPaper(UploadPaperRequest) returns (UploadPaperResponse);

  // 健康检查
  rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse);
}

// ========== Chat 相关消息 ==========

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

// ========== Upload 相关消息 ==========

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

// ========== Health 相关消息 ==========

message HealthCheckRequest {}

message HealthCheckResponse {
  bool healthy = 1;
  map<string, string> services = 2;
}
```

## 验收标准

完成后执行以下检查：

### 1. Proto 文件语法检查

```bash
# 安装 protoc（如果未安装）
# Windows: winget install protobuf
# macOS: brew install protobuf
# Linux: apt install protobuf-compiler

# 验证语法
protoc --proto_path=proto --descriptor_set_out=/dev/null proto/agent/v1/agent.proto
```

预期：无报错输出。

### 2. 生成 Go 代码

```bash
# 安装 Go protoc 插件
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

# 生成代码
mkdir -p gateway/internal/grpc/agentpb
protoc --proto_path=proto \
  --go_out=gateway/internal/grpc/agentpb \
  --go_opt=paths=source_relative \
  --go-grpc_out=gateway/internal/grpc/agentpb \
  --go-grpc_opt=paths=source_relative \
  proto/agent/v1/agent.proto
```

预期：生成 `gateway/internal/grpc/agentpb/agent.pb.go` 和 `agent_grpc.pb.go`。

### 3. 生成 Python 代码

```bash
# 安装 Python grpc 工具
pip install grpcio-tools

# 生成代码
mkdir -p agent/app/grpc/agentpb
python -m grpc_tools.protoc \
  --proto_path=proto \
  --python_out=agent/app/grpc/agentpb \
  --grpc_python_out=agent/app/grpc/agentpb \
  proto/agent/v1/agent.proto
```

预期：生成 `agent/app/grpc/agentpb/agent_pb2.py` 和 `agent_pb2_grpc.py`。

### 4. 验收 Checklist

- [ ] Proto 文件语法正确，`protoc` 编译无报错
- [ ] 成功生成 Go 代码（`*.pb.go` + `*_grpc.pb.go`）
- [ ] 成功生成 Python 代码（`*_pb2.py` + `*_pb2_grpc.py`）
- [ ] 文件路径符合项目结构约定
- [ ] `go_package` 路径正确指向 `gateway/internal/grpc/agentpb`

## 提交

验收通过后提交：

```bash
git add proto/ gateway/internal/grpc/agentpb/ agent/app/grpc/agentpb/
git commit -m "feat(proto): define gRPC interface for agent service

- Add Chat RPC with server streaming for token/status events
- Add UploadPaper RPC for PDF parsing
- Add HealthCheck RPC
- Generate Go and Python code from proto"
```

## 注意事项

1. `go_package` 路径必须与实际 Go module 路径一致
2. Python 生成的代码需要在 `agent/app/grpc/agentpb/__init__.py` 中导出（后续任务处理）
3. 如果 protoc 版本过低（< 3.15），可能不支持某些语法，建议升级到最新版

