# Codex 执行指令 — 任务 8.1：Docker 化部署

## 任务目标

为所有服务编写 Dockerfile 和 docker-compose.yml，实现一键启动。

## 前置依赖

- 所有模块代码已完成

## 需要创建的文件

### 1. `gateway/Dockerfile`

```dockerfile
FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /gateway ./cmd/server/

FROM alpine:3.19
RUN apk --no-cache add ca-certificates tzdata
WORKDIR /app
COPY --from=builder /gateway .
COPY configs/config.yaml ./configs/
EXPOSE 8080
CMD ["./gateway"]
```

### 2. `agent/Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 50051
CMD ["python", "-m", "app.main"]
```

### 3. `web/Dockerfile`

```dockerfile
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
```

### 4. `web/nginx.conf`

```nginx
server {
    listen 3000;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy API to gateway
    location /api/ {
        proxy_pass http://gateway:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Proxy WebSocket to gateway
    location /ws {
        proxy_pass http://gateway:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }
}
```

### 5. `docker-compose.yml`（项目根目录）

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: paper_agent
      POSTGRES_PASSWORD: paper_agent
      POSTGRES_DB: paper_agent
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U paper_agent"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  chroma:
    image: chromadb/chroma:latest
    ports:
      - "8000:8000"
    volumes:
      - chroma_data:/chroma/chroma

  agent-service:
    build: ./agent
    ports:
      - "50051:50051"
    environment:
      GRPC_PORT: "50051"
      LLM_PROVIDER: ${LLM_PROVIDER:-dashscope}
      LLM_API_KEY: ${LLM_API_KEY}
      LLM_MODEL: ${LLM_MODEL:-qwen-plus}
      EMBEDDING_MODEL: ${EMBEDDING_MODEL:-text-embedding-v3}
      REDIS_URL: redis://redis:6379/0
      CHROMA_HOST: chroma
      CHROMA_PORT: "8000"
    depends_on:
      redis:
        condition: service_healthy
      chroma:
        condition: service_started

  gateway:
    build: ./gateway
    ports:
      - "8080:8080"
    environment:
      REDIS_ADDR: redis:6379
      GRPC_AGENT_ADDR: agent-service:50051
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      POSTGRES_USER: paper_agent
      POSTGRES_PASSWORD: paper_agent
      POSTGRES_DBNAME: paper_agent
      GATEWAY_PORT: "8080"
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      agent-service:
        condition: service_started

  web:
    build: ./web
    ports:
      - "3000:3000"
    depends_on:
      - gateway

volumes:
  postgres_data:
  chroma_data:
```

### 6. `scripts/init.sql`

```sql
-- Paper Agent 数据库初始化脚本

CREATE TABLE IF NOT EXISTS papers (
    id          VARCHAR(64) PRIMARY KEY,
    title       TEXT NOT NULL,
    authors     TEXT[] NOT NULL,
    abstract    TEXT,
    year        INTEGER,
    source      VARCHAR(20) NOT NULL,
    doi         VARCHAR(128),
    url         TEXT,
    citation_count INTEGER DEFAULT 0,
    extracted_info JSONB,
    pdf_path    TEXT,
    is_indexed  BOOLEAN DEFAULT FALSE,
    file_hash   VARCHAR(32),
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_file_hash ON papers(file_hash);
CREATE INDEX IF NOT EXISTS idx_papers_extracted_info ON papers USING GIN(extracted_info);

CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       VARCHAR(200),
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL,
    content     TEXT NOT NULL,
    metadata    JSONB,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS research_projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    topic       TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'active',
    plan        JSONB,
    paper_ids   TEXT[],
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_projects_session ON research_projects(session_id);

CREATE TABLE IF NOT EXISTS uploaded_files (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    paper_id    VARCHAR(64) REFERENCES papers(id),
    filename    VARCHAR(255) NOT NULL,
    file_path   TEXT NOT NULL,
    file_size   BIGINT NOT NULL,
    file_hash   VARCHAR(32) NOT NULL,
    status      VARCHAR(20) DEFAULT 'uploaded',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_session ON uploaded_files(session_id);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_hash ON uploaded_files(file_hash);
```

### 7. `.env.example`（项目根目录）

```bash
# LLM Configuration (required)
LLM_PROVIDER=dashscope
LLM_API_KEY=sk-your-api-key-here
LLM_MODEL=qwen-plus
EMBEDDING_MODEL=text-embedding-v3
```

### 8. `.gitignore`（项目根目录）

```gitignore
# Dependencies
gateway/vendor/
web/node_modules/
web/dist/
agent/__pycache__/
agent/**/__pycache__/
agent/.venv/

# Environment
.env
*.env.local

# Uploads
uploads/

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
Thumbs.db

# Build
gateway/gateway
gateway/server

# Docker volumes
postgres_data/
chroma_data/
```

### 9. `Makefile`（项目根目录）

```makefile
.PHONY: up down build logs clean proto

# Start all services
up:
	docker-compose up -d

# Stop all services
down:
	docker-compose down

# Build all images
build:
	docker-compose build

# View logs
logs:
	docker-compose logs -f

# Clean volumes and images
clean:
	docker-compose down -v --rmi local

# Regenerate proto code
proto:
	protoc --proto_path=proto \
		--go_out=gateway/internal/grpc/agentpb --go_opt=paths=source_relative \
		--go-grpc_out=gateway/internal/grpc/agentpb --go-grpc_opt=paths=source_relative \
		proto/agent/v1/agent.proto
	python -m grpc_tools.protoc -Iproto \
		--python_out=agent/app/grpc/agentpb \
		--grpc_python_out=agent/app/grpc/agentpb \
		proto/agent/v1/agent.proto

# Dev: start infrastructure only
dev-infra:
	docker-compose up -d postgres redis chroma
```

## 验收标准

### 1. 构建检查

```bash
docker-compose build
```

预期：所有 5 个服务镜像构建成功。

### 2. 启动检查

```bash
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY
docker-compose up -d
```

预期：
- `docker-compose ps` 显示所有服务 running
- `curl http://localhost:8080/health` 返回状态
- 浏览器打开 http://localhost:3000 显示前端页面

### 3. 验收 Checklist

- [ ] 每个服务有独立 Dockerfile，构建成功
- [ ] `docker-compose up` 一键启动所有服务
- [ ] 服务间网络互通（gateway → agent gRPC, gateway → redis/postgres, agent → chroma/redis）
- [ ] 环境变量通过 `.env` 文件注入
- [ ] 前端 nginx 反向代理 `/api` → gateway，`/ws` → WebSocket
- [ ] PostgreSQL 初始化脚本自动执行（建表）
- [ ] 健康检查：postgres 和 redis 有 healthcheck，gateway 等待依赖就绪
- [ ] `make up` / `make down` / `make logs` 正常工作
- [ ] `.gitignore` 排除 node_modules、__pycache__、uploads、.env

## 提交

```bash
git add gateway/Dockerfile agent/Dockerfile web/Dockerfile web/nginx.conf \
  docker-compose.yml scripts/ .env.example .gitignore Makefile
git commit -m "feat: add Docker deployment with docker-compose

- Dockerfile for gateway (Go multi-stage), agent (Python), web (Vue + nginx)
- docker-compose with postgres, redis, chroma, agent, gateway, web
- PostgreSQL init script with all table schemas
- nginx reverse proxy for API and WebSocket
- Makefile shortcuts (up/down/build/logs/clean/proto)
- .env.example and .gitignore"
```
