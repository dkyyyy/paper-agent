# Paper Agent — 智能论文研究助手

## 项目简介

基于 LangGraph 多 Agent 协作的学术研究助手，支持文献检索、论文精读、方法对比、Research Gap 发现。

## 技术架构

- Go (Gin)：API 网关层（gateway/）
- Python (LangGraph + LangChain + MCP)：Agent 服务层（agent/）
- Vue3 + Vite + TypeScript + Element Plus：前端（web/）
- gRPC：Go ↔ Python 服务间通信
- Redis：会话管理 + 搜索缓存
- Chroma：论文向量存储
- LLM：通义千问 / 智谱 GLM

## 项目结构

```
paper-agent/
├── gateway/          # Go 后端网关（Gin, gRPC client, Redis）
├── agent/            # Python Agent 服务（LangGraph, MCP, RAG）
├── web/              # Vue3 前端（Vite, Element Plus, WebSocket）
├── proto/            # 共享 gRPC Proto 定义
├── docs/             # 项目文档（架构、规范、接口、验收标准）
├── docker-compose.yml
└── README.md
```

## 开发规范（必读）

开始任何开发任务前，必须先阅读以下文档：

- `docs/01-architecture.md` — 系统架构、模块划分、数据流
- `docs/02-dev-standards.md` — 编码规范、Agent 开发模板、MCP Server 模板、Prompt 规范
- `docs/03-task-acceptance.md` — 模块任务拆解与验收 checklist
- `docs/04-api-design.md` — HTTP/WebSocket/gRPC 接口定义、错误码

## 关键约束

1. Go 后端只做网关职责（路由、会话、文件上传、流式转发），不包含 Agent 逻辑
2. Python Agent 服务通过 gRPC Server Streaming 与 Go 通信，不直接暴露 HTTP
3. 每个 Agent 必须使用 LangGraph StateGraph 构建，遵循 docs/02-dev-standards.md 中的模板
4. 每个 MCP Server 必须遵循 docs/02-dev-standards.md 中的 MCP 开发模板
5. Prompt 集中管理在 agent/app/prompts/ 目录，不散落在业务代码中
6. 前端使用 Composition API + `<script setup lang="ts">`，不使用 Options API
7. 所有接口数据必须定义 TypeScript 类型，禁止 any
8. gRPC Proto 定义在 proto/ 目录，Go 和 Python 共享，修改后两端同步生成代码
9. 向量库 Collection 命名：papers_paragraph / papers_section / papers_summary
10. Redis key 前缀：session:{id} / search:{tool}:{hash}

## 开发流程

1. 开始任务前：阅读 docs/03-task-acceptance.md 找到对应任务
2. 开发过程中：严格按照 docs/02-dev-standards.md 的模板和规范
3. 完成任务后：逐条检查验收标准 checklist
4. 涉及接口变更：同步更新 docs/04-api-design.md 和 proto 定义

## Commit 规范

```
<type>(<scope>): <subject>

type: feat | fix | refactor | docs | test | chore
scope: gateway | agent | web | proto | docs
```
