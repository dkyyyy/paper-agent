# Paper Agent — 系统架构设计文档

## 1. 项目概述

### 1.1 项目定位
基于 LangGraph 多 Agent 协作的智能论文研究助手，支持文献检索、论文精读、方法对比、Research Gap 发现等学术研究全流程。

### 1.2 目标用户
研究生、科研工作者、技术调研人员。

### 1.3 核心场景

| 场景 | 用户输入 | 系统输出 |
|------|---------|---------|
| 文献调研 | "调研 2023-2025 RAG 优化的最新进展" | 文献综述 + 方法对比表 + 时间线 |
| 论文精读 | 上传 PDF + "分析核心方法和实验结果" | 结构化分析报告（五元组） |
| 方法对比 | "对比 RAG-Fusion、Self-RAG、CRAG" | 对比矩阵 + 适用场景建议 |
| Gap 发现 | "基于这些论文，还有哪些方向值得研究？" | 研究空白分析 + 方向建议 |

---

## 2. 技术选型

### 2.1 技术栈总览

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | Vue3 + Vite + TypeScript | 现代前端工程，Element Plus 组件库，WebSocket 流式通信 |
| API 网关 | Go (Gin) | HTTP/WebSocket 网关，会话管理，请求路由，鉴权 |
| Agent 服务 | Python (LangGraph + LangChain) | 多 Agent 编排，RAG 管线，LLM 调用 |
| 工具层 | MCP Protocol | 统一工具发现与调用协议 |
| 向量库 | Chroma | 论文向量存储与检索 |
| 缓存/会话 | Redis | 会话状态、搜索缓存、Token 预算追踪 |
| LLM | 通义千问 / 智谱 GLM | 国产模型，成本可控 |
| 通信 | gRPC | Go ↔ Python 服务间高效通信 |

### 2.2 为什么用 Go + Python 双服务架构

```
┌─────────────────────────────────────────────────────┐
│  为什么不全用 Python？                                │
│                                                      │
│  1. Go 网关层：高并发连接管理、WebSocket 长连接、      │
│     会话路由 —— Go 的并发模型天然适合                  │
│  2. Python Agent 层：LangGraph/LangChain 生态只在      │
│     Python，LLM 调用和 RAG 管线用 Python 最成熟        │
│  3. 面试加分：展示多语言架构能力和服务拆分思维          │
│  4. gRPC 通信：强类型接口定义，序列化高效               │
└─────────────────────────────────────────────────────┘
```

---

## 3. 系统架构

### 3.1 整体架构图

```
                    ┌──────────────────┐
                    │  Vue3 + Vite     │
                    │  前端 SPA         │
                    └──────┬───────────┘
                           │ HTTP / WebSocket
                           ▼
              ┌────────────────────────┐
              │   Go API Gateway       │
              │   (Gin Framework)      │
              │                        │
              │  ┌──────────────────┐  │
              │  │ 会话管理 (Redis)  │  │
              │  │ 请求路由          │  │
              │  │ 文件上传处理      │  │
              │  │ 流式响应转发      │  │
              │  │ 健康检查/监控     │  │
              │  └──────────────────┘  │
              └────────────┬───────────┘
                           │ gRPC
                           ▼
              ┌────────────────────────┐
              │  Python Agent Service  │
              │                        │
              │  ┌──────────────────┐  │
              │  │ Supervisor Agent │  │
              │  │ (LangGraph 状态机)│  │
              │  └──┬─────┬─────┬──┘  │
              │     │     │     │      │
              │     ▼     ▼     ▼      │
              │  ┌─────┐┌────┐┌─────┐  │
              │  │检索  ││分析││综合  │  │
              │  │Agent ││Agent││Agent│  │
              │  └──┬──┘└─┬──┘└──┬──┘  │
              │     │     │      │     │
              │     ▼     ▼      ▼     │
              │  ┌──────────────────┐  │
              │  │   MCP Tool Layer │  │
              │  │ ┌──────────────┐ │  │
              │  │ │ArXiv Server  │ │  │
              │  │ │S2 Server     │ │  │
              │  │ │DBLP Server   │ │  │
              │  │ │PDF Parser    │ │  │
              │  │ └──────────────┘ │  │
              │  └──────────────────┘  │
              └────────────────────────┘
                     │          │
                     ▼          ▼
              ┌──────────┐ ┌────────┐
              │  Chroma  │ │ Redis  │
              │ 向量存储  │ │ 缓存   │
              └──────────┘ └────────┘
```

### 3.2 请求流转示例（文献调研场景）

```
1. 用户在 Vue 前端输入 "调研 RAG 优化最新进展"
2. 前端通过 WebSocket → Go Gateway
3. Go Gateway 创建/恢复会话 → 通过 gRPC 调用 Python Agent Service
4. Supervisor Agent 接收请求：
   a. 意图识别 → "文献调研"
   b. 生成研究计划：关键词提取、搜索范围、预期输出格式
   c. 分发给 Search Agent
5. Search Agent 执行：
   a. 调用 arxiv_search MCP 工具 → 获取 20 篇候选
   b. 调用 semantic_scholar_search → 获取 30 篇候选
   c. 去重合并 → 相关性排序 → 取 Top 15
   d. 评估覆盖度 → 不足则自动扩展关键词重新搜索
   e. 返回结构化论文列表
6. Supervisor 将论文列表分发给 Analysis Agent（可并行）
7. Analysis Agent 对每篇论文：
   a. 提取五元组（Research Question, Method, Dataset, Metric, Result）
   b. 生成章节级摘要
   c. 向量化入库 Chroma
8. Supervisor 将分析结果交给 Synthesis Agent
9. Synthesis Agent：
   a. 生成方法对比表格
   b. 按时间线梳理研究脉络
   c. 生成文献综述段落
10. Supervisor 质量检查 → 通过 → 返回给 Go Gateway
11. Go Gateway 流式转发给前端 → 用户看到打字机效果输出
```

---

## 4. 模块划分

### 4.1 Go 后端服务（paper-agent-gateway）

```
gateway/
├── cmd/
│   └── server/
│       └── main.go              # 入口
├── internal/
│   ├── config/
│   │   └── config.go            # 配置加载（YAML）
│   ├── handler/
│   │   ├── chat.go              # 聊天接口（HTTP + WebSocket）
│   │   ├── upload.go            # PDF 上传接口
│   │   ├── session.go           # 会话管理接口
│   │   └── health.go            # 健康检查
│   ├── middleware/
│   │   ├── cors.go              # 跨域
│   │   ├── ratelimit.go         # 限流
│   │   └── logging.go           # 请求日志
│   ├── service/
│   │   ├── session.go           # 会话业务逻辑（Redis）
│   │   ├── agent_client.go      # gRPC 客户端（调用 Python）
│   │   └── file.go              # 文件存储管理
│   ├── model/
│   │   ├── chat.go              # 请求/响应模型
│   │   └── session.go           # 会话模型
│   └── grpc/
│       └── proto/
│           └── agent.proto      # gRPC 接口定义
├── configs/
│   └── config.yaml              # 配置文件
├── go.mod
└── go.sum
```

### 4.2 Python Agent 服务（paper-agent-agent）

```
agent/
├── app/
│   ├── main.py                  # gRPC Server 入口
│   ├── config.py                # 配置管理
│   ├── grpc_server.py           # gRPC 服务实现
│   ├── agents/
│   │   ├── supervisor.py        # Supervisor Agent
│   │   ├── search_agent.py      # 文献检索 Agent
│   │   ├── analysis_agent.py    # 论文分析 Agent
│   │   ├── synthesis_agent.py   # 综合报告 Agent
│   │   └── graph.py             # LangGraph 工作流定义
│   ├── mcp_servers/
│   │   ├── arxiv_server.py      # ArXiv MCP Server
│   │   ├── semantic_scholar.py  # Semantic Scholar MCP Server
│   │   ├── dblp_server.py       # DBLP MCP Server
│   │   └── pdf_parser.py        # PDF 解析 MCP Server
│   ├── rag/
│   │   ├── chunker.py           # 论文分块策略
│   │   ├── embeddings.py        # 向量化
│   │   ├── retriever.py         # 分层检索器
│   │   └── indexer.py           # 增量索引（MD5 去重）
│   ├── services/
│   │   ├── cache.py             # Redis 缓存封装
│   │   └── token_budget.py      # Token 预算控制
│   └── prompts/
│       ├── supervisor.py        # 调度 Prompt
│       ├── search.py            # 检索 Prompt
│       ├── analysis.py          # 分析 Prompt
│       └── synthesis.py         # 综合 Prompt
├── proto/
│   └── agent.proto              # gRPC 接口定义（与 Go 共享）
├── tests/
├── requirements.txt
└── Dockerfile
```

### 4.3 前端（paper-agent-web）

```
web/
├── public/
├── src/
│   ├── api/
│   │   ├── chat.ts              # 聊天接口（WebSocket + REST）
│   │   ├── session.ts           # 会话管理接口
│   │   └── upload.ts            # 文件上传接口
│   ├── components/
│   │   ├── ChatPanel/
│   │   │   ├── ChatPanel.vue    # 聊天主面板
│   │   │   ├── MessageBubble.vue # 消息气泡（支持 Markdown 渲染）
│   │   │   └── InputBar.vue     # 输入栏（文本 + 文件上传）
│   │   ├── ReportView/
│   │   │   ├── ReportView.vue   # 报告展示（文献综述/对比表）
│   │   │   ├── ComparisonTable.vue # 方法对比表格
│   │   │   └── Timeline.vue     # 研究时间线
│   │   ├── Sidebar/
│   │   │   ├── SessionList.vue  # 会话历史列表
│   │   │   └── PaperList.vue    # 已检索论文列表
│   │   └── common/
│   │       ├── MarkdownRenderer.vue # Markdown 渲染器
│   │       └── LoadingIndicator.vue # Agent 执行状态指示
│   ├── composables/
│   │   ├── useWebSocket.ts      # WebSocket 连接管理
│   │   ├── useSession.ts        # 会话状态管理
│   │   └── useStreaming.ts      # 流式响应处理
│   ├── stores/
│   │   ├── chat.ts              # 聊天状态（Pinia）
│   │   └── session.ts           # 会话状态（Pinia）
│   ├── views/
│   │   ├── ChatView.vue         # 主聊天页
│   │   └── HistoryView.vue      # 历史会话页
│   ├── router/
│   │   └── index.ts
│   ├── App.vue
│   └── main.ts
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
└── Dockerfile
```

---

## 5. 数据流与状态管理

### 5.1 会话状态（Redis）

```json
{
  "session_id": "uuid",
  "user_id": "anonymous",
  "created_at": "2025-01-15T10:00:00Z",
  "ttl": 3600,
  "research_context": {
    "topic": "RAG optimization",
    "papers_found": ["paper_id_1", "paper_id_2"],
    "papers_analyzed": ["paper_id_1"],
    "current_step": "analysis",
    "research_plan": { ... }
  },
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "token_usage": {
    "total": 15000,
    "budget": 50000
  }
}
```

### 5.2 论文数据模型

```json
{
  "paper_id": "arxiv:2401.12345",
  "title": "...",
  "authors": ["..."],
  "abstract": "...",
  "year": 2024,
  "source": "arxiv",
  "doi": "...",
  "citation_count": 42,
  "extracted_info": {
    "research_question": "...",
    "method": "...",
    "dataset": ["..."],
    "metrics": {"...": "..."},
    "results": "..."
  },
  "chunks": [
    {"id": "chunk_1", "level": "paragraph", "content": "...", "section": "method"}
  ]
}
```

---

## 6. 部署架构

```
docker-compose.yml
├── gateway        (Go, port 8080)
├── agent-service  (Python, gRPC port 50051)
├── redis          (port 6379)
├── chroma         (port 8000)
└── web            (Vue3, port 3000, nginx 托管)
```

所有服务容器化，`docker-compose up` 一键启动，面试演示友好。
