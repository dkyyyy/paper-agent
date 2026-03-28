# Codex 执行指令 — 任务 3.1：Python gRPC Server 骨架

## 任务目标

实现 Python gRPC Server，接收 ChatRequest，调用 LangGraph 工作流，流式返回 ChatEvent。当前先搭骨架，返回 mock 数据。

## 前置依赖

- 任务 1.1 已完成（Proto 定义 + Python 生成代码在 `agent/app/grpc/agentpb/`）

## 需要创建的文件

### 1. `agent/requirements.txt`

```
grpcio==1.68.0
grpcio-tools==1.68.0
langchain>=0.3.0
langchain-core>=0.3.0
langgraph>=0.2.0
langchain-community>=0.3.0
chromadb>=0.5.0
redis>=5.0.0
PyMuPDF>=1.24.0
pydantic>=2.0.0
python-dotenv>=1.0.0
dashscope>=1.20.0
```

### 2. `agent/app/config.py`

```python
"""Application configuration loaded from environment variables."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # gRPC
    grpc_port: int = int(os.getenv("GRPC_PORT", "50051"))

    # LLM
    llm_provider: str = os.getenv("LLM_PROVIDER", "dashscope")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "qwen-plus")

    # Embedding
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")

    # Redis
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Chroma
    chroma_host: str = os.getenv("CHROMA_HOST", "localhost")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8000"))

    # Upload
    upload_dir: str = os.getenv("UPLOAD_DIR", "./uploads")


config = Config()
```

### 3. `agent/app/grpc_server.py`

```python
"""gRPC server implementation for the Agent service."""

import logging
from concurrent import futures

import grpc

from app.grpc.agentpb import agent_pb2, agent_pb2_grpc

logger = logging.getLogger(__name__)


class AgentServicer(agent_pb2_grpc.AgentServiceServicer):
    """Implements the AgentService gRPC interface."""

    def Chat(self, request, context):
        """Handle chat request with streaming response.

        Currently returns mock events. Will be replaced with LangGraph
        workflow invocation in task 3.2.
        """
        session_id = request.session_id
        content = request.content
        logger.info(f"Chat request: session={session_id}, content={content[:50]}")

        # Mock: send agent_status event
        yield agent_pb2.ChatEvent(
            event_type=agent_pb2.EVENT_TYPE_AGENT_STATUS,
            agent_name="supervisor",
            step_description="正在分析您的需求...",
        )

        # Mock: send token events
        mock_response = f"收到您的问题：「{content}」。系统正在开发中，这是一条模拟回复。"
        for char in mock_response:
            yield agent_pb2.ChatEvent(
                event_type=agent_pb2.EVENT_TYPE_TOKEN,
                content=char,
            )

        # Mock: send done event
        yield agent_pb2.ChatEvent(
            event_type=agent_pb2.EVENT_TYPE_DONE,
            content=mock_response,
        )

    def UploadPaper(self, request, context):
        """Handle paper upload and parsing.

        Currently returns mock response. Will be replaced with actual
        PDF parsing in task 4.4.
        """
        logger.info(f"UploadPaper: session={request.session_id}, file={request.filename}")

        return agent_pb2.UploadPaperResponse(
            paper_id=f"mock_{request.filename}",
            title=f"Mock Title for {request.filename}",
            page_count=10,
            success=True,
        )

    def HealthCheck(self, request, context):
        """Report service health."""
        return agent_pb2.HealthCheckResponse(
            healthy=True,
            services={"llm": "ok", "chroma": "ok", "redis": "ok"},
        )


def create_server(port: int, max_workers: int = 10) -> grpc.Server:
    """Create and configure the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    return server
```

### 4. `agent/app/main.py`

```python
"""Entry point for the Python Agent gRPC service."""

import logging
import signal
import sys
from concurrent import futures

from app.config import config
from app.grpc_server import create_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    port = config.grpc_port
    server = create_server(port)
    server.start()
    logger.info(f"Agent gRPC server started on port {port}")

    # Graceful shutdown
    def shutdown(signum, frame):
        logger.info("Shutting down gracefully...")
        event = server.stop(grace=10)  # Wait up to 10s for in-flight requests
        event.wait()
        logger.info("Server stopped")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    server.wait_for_termination()


if __name__ == "__main__":
    main()
```

### 5. `agent/app/__init__.py`

空文件，使 `app` 成为 Python 包。

```python
```

### 6. `agent/.env.example`

```bash
# gRPC
GRPC_PORT=50051

# LLM
LLM_PROVIDER=dashscope
LLM_API_KEY=sk-xxx
LLM_MODEL=qwen-plus

# Embedding
EMBEDDING_MODEL=text-embedding-v3

# Redis
REDIS_URL=redis://localhost:6379/0

# Chroma
CHROMA_HOST=localhost
CHROMA_PORT=8000

# Upload
UPLOAD_DIR=./uploads
```

## 验收标准

### 1. 依赖安装

```bash
cd agent
pip install -r requirements.txt
```

### 2. 启动检查

```bash
cd agent
python -m app.main
```

预期：
- 控制台输出 `Agent gRPC server started on port 50051`
- 进程不退出，等待请求

### 3. gRPC 调用测试（需要 grpcurl 或 Go Gateway）

如果安装了 grpcurl：
```bash
grpcurl -plaintext -d '{}' localhost:50051 agent.v1.AgentService/HealthCheck
```

预期返回：
```json
{"healthy": true, "services": {"llm": "ok", "chroma": "ok", "redis": "ok"}}
```

### 4. 优雅关闭测试

启动服务后按 Ctrl+C，预期：
- 输出 "Shutting down gracefully..."
- 输出 "Server stopped"
- 进程正常退出

### 5. 验收 Checklist

- [ ] `pip install -r requirements.txt` 安装成功
- [ ] `python -m app.main` 启动成功，监听 50051 端口
- [ ] HealthCheck RPC 返回 healthy=true
- [ ] Chat RPC 流式返回 agent_status → 多个 token → done 事件
- [ ] UploadPaper RPC 返回 mock 解析结果
- [ ] Ctrl+C 优雅关闭，等待进行中请求完成
- [ ] 配置通过环境变量加载，支持 .env 文件

## 提交

```bash
git add agent/
git commit -m "feat(agent): init Python gRPC server with mock responses

- gRPC server on port 50051 with AgentServicer
- Mock Chat streaming (agent_status → tokens → done)
- Mock UploadPaper and HealthCheck responses
- Config from environment variables with .env support
- Graceful shutdown on SIGTERM/SIGINT"
```

## 注意事项

1. 确保 `agent/app/grpc/agentpb/__init__.py` 存在（任务 1.1 应已创建）
2. 运行时需要从 `agent/` 目录执行 `python -m app.main`
3. Mock 响应会在后续任务（3.2-3.5）中替换为真实 LangGraph 工作流
