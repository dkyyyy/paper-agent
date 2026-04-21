# Paper Agent

基于 LangGraph 多 Agent 协作的智能论文研究助手，支持文献检索、论文精读、方法对比、Research Gap 发现。

## 功能

| 场景 | 输入 | 输出 |
|------|------|------|
| 文献调研 | "调研 2023-2025 RAG 优化的最新进展" | 文献综述 + 方法对比表 + 时间线 |
| 论文精读 | 上传 PDF + "分析核心方法和实验结果" | 结构化分析报告（五元组） |
| 方法对比 | "对比 RAG-Fusion、Self-RAG、CRAG" | 对比矩阵 + 适用场景建议 |
| Gap 发现 | "基于这些论文，还有哪些方向值得研究？" | 研究空白分析 + 方向建议 |

## 技术架构

```
Vue3 前端
    │ WebSocket
    ▼
Go API Gateway (Gin)          # 会话管理、文件上传、流式转发
    │ gRPC Server Streaming
    ▼
Python Agent Service (LangGraph)
    ├── Supervisor             # 意图识别 + 任务编排 + 质量检查
    ├── Planner                # 查询拆解为子问题
    ├── SearchAgent            # 多源文献检索（ArXiv + Semantic Scholar）
    ├── AnalysisAgent          # 论文五元组提取 + 向量入库
    ├── SynthesisAgent         # 报告生成 + RAG 问答
    └── ComparisonAgent        # 方法对比专用流程
         │
         ▼ MCP Protocol
    ┌────────────────────┐
    │ ArXiv MCP Server   │
    │ S2 MCP Server      │
    │ PDF Parser Server  │
    └────────────────────┘
         │
    ┌────┴────┐
  Chroma   Redis   PostgreSQL
  向量存储  热缓存   持久化
```

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Vue3 + Vite + TypeScript + Element Plus |
| 网关 | Go + Gin + gRPC Client |
| Agent 服务 | Python + LangGraph + LangChain |
| 工具层 | MCP Protocol (stdio) |
| 向量库 | Chroma（段落 / 章节 / 摘要三粒度） |
| 缓存 | Redis（会话热数据 + 搜索缓存，TTL 1h） |
| 持久化 | PostgreSQL（会话历史 + 论文元数据） |
| LLM | 通义千问 / 智谱 GLM / DeepSeek |
| 通信 | gRPC Server Streaming |

## 快速启动

**依赖：** Docker + Docker Compose

```bash
# 1. 配置环境变量
cp .env.example .env
# 填入 LLM API Key（DASHSCOPE_API_KEY 或 ZHIPUAI_API_KEY）

# 2. 启动所有服务
docker compose up -d

# 3. 访问
# 前端：http://localhost:3000
# API：http://localhost:8080
```

## 项目结构

```
paper-agent/
├── gateway/          # Go 网关（Gin, gRPC client, Redis, PostgreSQL）
├── agent/            # Python Agent 服务
│   └── app/
│       ├── agents/       # Supervisor / Search / Analysis / Synthesis / Comparison / Planner
│       ├── mcp_servers/  # ArXiv / Semantic Scholar / PDF Parser MCP Server
│       ├── rag/          # 分块 / 向量化 / 分层检索
│       ├── services/     # PostgreSQL / Redis / Token 预算
│       └── prompts/      # 集中管理的 Prompt 模板
├── web/              # Vue3 前端
├── proto/            # gRPC Proto 定义
├── docker/           # init.sql 等初始化脚本
└── docs/             # 架构文档 / API 设计 / 开发规范
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DASHSCOPE_API_KEY` | 通义千问 API Key | — |
| `ZHIPUAI_API_KEY` | 智谱 GLM API Key | — |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | — |
| `POSTGRES_PASSWORD` | PostgreSQL 密码 | `paperagent` |
| `REDIS_URL` | Redis 连接地址 | `redis://redis:6379` |
| `CHROMA_HOST` | Chroma 服务地址 | `chroma` |
| `SEMANTIC_SCHOLAR_API_KEY` | S2 API Key（可选，提升限速） | — |

完整配置见 `.env.example`。
