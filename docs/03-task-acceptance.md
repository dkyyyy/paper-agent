# Paper Agent — 模块任务拆解与验收标准

> 每个任务设计为可独立交给 Codex 执行的粒度，包含明确的输入、输出、验收条件。

---

## 模块 1：gRPC Proto 定义

### 任务 1.1：定义 Agent 服务 Proto

**文件**：`proto/agent/v1/agent.proto`

**功能描述**：
定义 Go Gateway 与 Python Agent Service 之间的 gRPC 通信接口。

**接口定义**：

```protobuf
syntax = "proto3";
package agent.v1;

service AgentService {
  // 流式对话：客户端发送一条消息，服务端流式返回多个事件
  rpc Chat(ChatRequest) returns (stream ChatEvent);

  // 上传论文：传入文件内容，返回解析结果
  rpc UploadPaper(UploadPaperRequest) returns (UploadPaperResponse);
}

message ChatRequest {
  string session_id = 1;
  string content = 2;
  repeated string attachment_ids = 3;  // 已上传的文件 ID
}

message ChatEvent {
  string event_type = 1;  // token | agent_status | done | error
  string content = 2;     // 文本内容（token 事件）
  string agent_name = 3;  // 当前执行的 Agent 名称
  string step = 4;        // 当前步骤描述
  string error = 5;       // 错误信息（error 事件）
}

message UploadPaperRequest {
  string session_id = 1;
  string filename = 2;
  bytes content = 3;
}

message UploadPaperResponse {
  string paper_id = 1;
  string title = 2;
  int32 page_count = 3;
  string status = 4;  // success | failed
  string error = 5;
}
```

**验收标准**：
- [ ] Proto 文件语法正确，`protoc` 编译无报错
- [ ] 成功生成 Go 代码（`*.pb.go` + `*_grpc.pb.go`）
- [ ] 成功生成 Python 代码（`*_pb2.py` + `*_pb2_grpc.py`）

---

## 模块 2：Go Gateway 服务

### 任务 2.1：项目初始化与配置管理

**文件**：`gateway/cmd/server/main.go`, `gateway/internal/config/config.go`, `gateway/configs/config.yaml`

**功能描述**：
初始化 Go 项目，实现 YAML 配置加载（Viper），包含 Redis、gRPC、服务端口等配置项。

**验收标准**：
- [ ] `go build` 编译通过
- [ ] 配置文件加载正确，支持环境变量覆盖
- [ ] 启动时打印配置摘要日志（脱敏）

### 任务 2.2：Redis 会话管理

**文件**：`gateway/internal/service/session.go`, `gateway/internal/model/session.go`

**功能描述**：
实现基于 Redis 的会话 CRUD，包括创建会话、获取会话、更新消息历史、设置 TTL 过期。

**接口定义**：
```go
type SessionService interface {
    Create(ctx context.Context) (*Session, error)
    Get(ctx context.Context, sessionID string) (*Session, error)
    AppendMessage(ctx context.Context, sessionID string, msg Message) error
    Delete(ctx context.Context, sessionID string) error
    List(ctx context.Context) ([]*SessionSummary, error)
}
```

**验收标准**：
- [ ] 创建会话返回 UUID，Redis 中可查到对应 key
- [ ] 会话 1 小时后自动过期（TTL）
- [ ] AppendMessage 正确追加消息到会话历史
- [ ] List 返回所有未过期会话的摘要（ID + 创建时间 + 最后消息预览）
- [ ] 单元测试覆盖所有方法

### 任务 2.3：gRPC 客户端封装

**文件**：`gateway/internal/service/agent_client.go`

**功能描述**：
封装 Python Agent Service 的 gRPC 客户端，支持流式接收 ChatEvent。

**验收标准**：
- [ ] 连接 Python gRPC Server 成功
- [ ] 流式接收 ChatEvent 并逐条返回
- [ ] 连接失败时有超时和重试机制（3 次重试，指数退避）
- [ ] 支持 Context 取消（用户断开时停止接收）

### 任务 2.4：HTTP 聊天接口

**文件**：`gateway/internal/handler/chat.go`

**功能描述**：
实现 `POST /api/v1/chat` 接口（SSE 流式响应）和 `GET /ws` WebSocket 接口。

**接口规格**：
```
POST /api/v1/chat
Content-Type: application/json
Body: { "session_id": "uuid", "content": "...", "attachment_ids": [] }
Response: text/event-stream (SSE)

GET /ws?session_id=uuid
Upgrade: websocket
```

**验收标准**：
- [ ] SSE 接口：发送消息后流式返回 Agent 事件，`event: token\ndata: {...}\n\n` 格式
- [ ] WebSocket 接口：建立连接后双向通信正常
- [ ] 无 session_id 时自动创建新会话
- [ ] 请求参数校验（content 不能为空）
- [ ] CORS 中间件正确配置

### 任务 2.5：文件上传接口

**文件**：`gateway/internal/handler/upload.go`, `gateway/internal/service/file.go`

**功能描述**：
实现 PDF 文件上传，存储到本地磁盘（`uploads/` 目录），通过 gRPC 通知 Agent 服务解析。

**接口规格**：
```
POST /api/v1/upload
Content-Type: multipart/form-data
Fields: session_id, file (PDF, max 20MB)
Response: { "code": 0, "data": { "paper_id": "...", "title": "...", "page_count": 10 } }
```

**验收标准**：
- [ ] 仅接受 PDF 文件，其他格式返回 400
- [ ] 文件大小限制 20MB，超出返回 413
- [ ] 文件保存到 `uploads/{session_id}/{uuid}.pdf`
- [ ] 调用 gRPC UploadPaper 成功并返回解析结果
- [ ] 上传失败时清理已保存的文件

### 任务 2.6：健康检查与中间件

**文件**：`gateway/internal/handler/health.go`, `gateway/internal/middleware/*.go`

**功能描述**：
实现健康检查端点、CORS、请求日志、限流中间件。

**验收标准**：
- [ ] `GET /health` 返回 `{"status": "ok", "redis": "connected", "agent": "connected"}`
- [ ] CORS 允许前端域名访问
- [ ] 每个请求打印结构化日志（method, path, status, latency）
- [ ] 限流：单 IP 每分钟 60 次请求

---

## 模块 3：Python Agent 服务

### 任务 3.1：gRPC Server 骨架

**文件**：`agent/app/main.py`, `agent/app/grpc_server.py`, `agent/app/config.py`

**功能描述**：
实现 Python gRPC Server，接收 ChatRequest，调用 LangGraph 工作流，流式返回 ChatEvent。

**验收标准**：
- [ ] gRPC Server 在 50051 端口启动
- [ ] 接收 ChatRequest 后能返回至少一个 ChatEvent（可先返回 mock 数据）
- [ ] 流式返回：每个事件独立发送，不等全部完成
- [ ] 优雅关闭：收到 SIGTERM 后等待进行中的请求完成

### 任务 3.2：Supervisor Agent

**文件**：`agent/app/agents/supervisor.py`, `agent/app/agents/graph.py`, `agent/app/prompts/supervisor.py`

**功能描述**：
实现主调度 Agent，负责意图识别、任务拆解、子 Agent 调度、结果质量评估。

**LangGraph 状态机**：
```
START → intent_recognition → task_planning → dispatch → aggregate → quality_check
                                                                        │
                                                              ┌─────────┤
                                                              ▼         ▼
                                                           pass → END  fail → re_plan → dispatch
```

**State 定义**：
```python
class SupervisorState(TypedDict):
    messages: list              # 用户消息历史
    intent: str                 # 识别的意图
    research_plan: list[dict]   # 任务计划
    sub_results: dict           # 子 Agent 返回结果
    final_output: str           # 最终输出
    iteration: int              # 重试次数
    max_iterations: int         # 最大重试（默认 2）
```

**验收标准**：
- [ ] 正确识别四种意图：文献调研、论文精读、方法对比、Gap 发现
- [ ] 生成结构化任务计划（JSON 格式）
- [ ] 按计划依次调用子 Agent（或并行调用无依赖的子 Agent）
- [ ] 质量检查不通过时触发重新规划（最多重试 2 次）
- [ ] 每个步骤通过回调发送 agent_status 事件

### 任务 3.3：Search Agent（文献检索）

**文件**：`agent/app/agents/search_agent.py`, `agent/app/prompts/search.py`

**功能描述**：
实现文献检索 Agent，支持多源搜索、自适应查询扩展、结果去重排序。

**LangGraph 状态机**：
```
START → plan_search → execute_search → evaluate → [continue: plan_search | done: END]
```

**State 定义**：
```python
class SearchState(TypedDict):
    query: str                  # 原始查询
    keywords: list[str]         # 提取的关键词
    search_queries: list[str]   # 已执行的搜索 query
    raw_results: list[dict]     # 原始搜索结果
    papers: list[Paper]         # 去重排序后的论文列表
    iteration: int
    max_iterations: int         # 默认 3
    target_count: int           # 目标论文数量（默认 15）
```

**验收标准**：
- [ ] 调用 ArXiv MCP 工具搜索并返回结果
- [ ] 调用 Semantic Scholar MCP 工具搜索并返回结果
- [ ] 多源结果基于 DOI / 标题相似度去重
- [ ] 结果按相关性排序（引用数 + 年份 + 关键词匹配度）
- [ ] 首轮结果不足时自动扩展关键词重新搜索（最多 3 轮）
- [ ] 返回结构化 Paper 列表（含 title, authors, abstract, year, source, citation_count）

### 任务 3.4：Analysis Agent（论文分析）

**文件**：`agent/app/agents/analysis_agent.py`, `agent/app/prompts/analysis.py`

**功能描述**：
实现论文深度分析 Agent，支持 PDF 解析、五元组提取、分层向量化。

**State 定义**：
```python
class AnalysisState(TypedDict):
    paper_id: str
    paper_content: str          # PDF 解析后的全文
    chunks: list[dict]          # 分块结果
    extracted_info: dict        # 五元组
    summary: str                # 章节级摘要
    indexed: bool               # 是否已入库
```

**验收标准**：
- [ ] 调用 PDF Parser MCP 工具解析 PDF，提取全文文本
- [ ] 按三层策略分块（段落 512 / 章节 2048 / 论文级摘要）
- [ ] 用 LLM 提取五元组：Research Question, Method, Dataset, Metric, Result
- [ ] 分块向量化后存入 Chroma（metadata 包含 paper_id, section, level）
- [ ] MD5 哈希去重：相同论文不重复解析和入库
- [ ] 返回结构化分析结果

### 任务 3.5：Synthesis Agent（综合报告）

**文件**：`agent/app/agents/synthesis_agent.py`, `agent/app/prompts/synthesis.py`

**功能描述**：
实现跨论文综合分析 Agent，生成对比报告、文献综述、Research Gap 分析。

**State 定义**：
```python
class SynthesisState(TypedDict):
    papers: list[dict]          # 已分析的论文列表（含五元组）
    task_type: str              # comparison | survey | gap_analysis
    output: str                 # 生成的报告（Markdown）
    comparison_table: str       # 对比表格（Markdown）
    timeline: str               # 时间线（Markdown）
```

**验收标准**：
- [ ] 方法对比：生成 Markdown 表格，列包含 论文/方法/数据集/指标/结果/优缺点
- [ ] 文献综述：生成 3-5 段结构化综述，包含引用标注 [1][2]
- [ ] 时间线：按年份梳理研究脉络
- [ ] Research Gap：基于已有论文分析，输出 3-5 个潜在研究方向
- [ ] 所有输出为合法 Markdown 格式

---

## 模块 4：MCP 工具服务

### 任务 4.1：ArXiv MCP Server

**文件**：`agent/app/mcp_servers/arxiv_server.py`

**外部依赖**：ArXiv API（https://info.arxiv.org/help/api/index.html），免费无需 key

**提供工具**：
| 工具名 | 输入 | 输出 |
|--------|------|------|
| `arxiv_search` | query, max_results, sort_by | 论文列表（id, title, authors, abstract, published, categories） |
| `arxiv_fetch` | arxiv_id | 单篇论文详情 + PDF 下载链接 |

**验收标准**：
- [ ] `arxiv_search("retrieval augmented generation", max_results=10)` 返回 10 篇论文
- [ ] 返回数据包含所有必要字段
- [ ] 网络超时 30s，超时返回错误而非挂起
- [ ] 支持 MCP 标准协议（list_tools + call_tool）

### 任务 4.2：Semantic Scholar MCP Server

**文件**：`agent/app/mcp_servers/semantic_scholar.py`

**外部依赖**：Semantic Scholar API（https://api.semanticscholar.org/），免费（有速率限制）

**提供工具**：
| 工具名 | 输入 | 输出 |
|--------|------|------|
| `s2_search` | query, max_results, year_range, fields_of_study | 论文列表 |
| `s2_paper_detail` | paper_id | 论文详情（含引用数、参考文献列表） |
| `s2_citations` | paper_id, limit | 引用该论文的论文列表 |
| `s2_references` | paper_id, limit | 该论文引用的论文列表 |

**验收标准**：
- [ ] 搜索返回结果包含 paperId, title, abstract, year, citationCount, authors
- [ ] 引用链查询正常工作
- [ ] 速率限制处理：429 响应时自动等待重试
- [ ] 支持 year_range 过滤

### 任务 4.3：DBLP MCP Server

**文件**：`agent/app/mcp_servers/dblp_server.py`

**外部依赖**：DBLP API（https://dblp.org/faq/How+to+use+the+dblp+search+API.html），免费

**提供工具**：
| 工具名 | 输入 | 输出 |
|--------|------|------|
| `dblp_search` | query, max_results | 论文列表（title, authors, venue, year, doi） |

**验收标准**：
- [ ] 搜索返回结果包含 title, authors, venue, year
- [ ] 返回的 DOI 可用于跨源去重
- [ ] 网络超时处理

### 任务 4.4：PDF Parser MCP Server

**文件**：`agent/app/mcp_servers/pdf_parser.py`

**外部依赖**：PyMuPDF (fitz)，本地解析

**提供工具**：
| 工具名 | 输入 | 输出 |
|--------|------|------|
| `parse_pdf` | file_path | 全文文本 + 章节结构 + 元数据（标题、作者、页数） |
| `extract_tables` | file_path, page_numbers | 表格数据（列表格式） |

**验收标准**：
- [ ] 解析 10 页 PDF 耗时 < 5s
- [ ] 正确提取全文文本，保留段落结构
- [ ] 识别章节标题（Introduction, Method, Experiment, Conclusion 等）
- [ ] 提取论文元数据（标题、作者）
- [ ] 文件不存在或格式错误时返回明确错误

---

## 模块 5：RAG 管线

### 任务 5.1：论文分块器

**文件**：`agent/app/rag/chunker.py`

**功能描述**：
实现三层分块策略（段落级 / 章节级 / 论文级）。

**验收标准**：
- [ ] 段落级：按 `\n\n` 分割，chunk_size=512，overlap=50
- [ ] 章节级：按章节标题分割，chunk_size=2048，overlap=200
- [ ] 论文级：调用 LLM 生成 ≤500 token 的论文摘要
- [ ] 每个 chunk 携带 metadata：paper_id, level, section, chunk_index

### 任务 5.2：向量化与索引

**文件**：`agent/app/rag/embeddings.py`, `agent/app/rag/indexer.py`

**功能描述**：
实现向量化和 Chroma 增量索引，支持 MD5 去重。

**验收标准**：
- [ ] 使用通义千问 text-embedding-v3 或 BGE 模型生成向量
- [ ] Chroma 中创建三个 Collection：`papers_paragraph`, `papers_section`, `papers_summary`
- [ ] 增量索引：计算文件 MD5，已存在则跳过
- [ ] 索引 100 个 chunk 耗时 < 30s

### 任务 5.3：分层检索器

**文件**：`agent/app/rag/retriever.py`

**功能描述**：
根据问题类型自动选择检索层级，返回相关文档。

**检索策略**：
```
问题类型判断（LLM）→ 选择层级 → 向量检索 → 重排序 → 返回 Top-K
```

**验收标准**：
- [ ] 细节问题（"用了什么 loss？"）→ 命中段落级 Collection
- [ ] 方法问题（"核心方法是什么？"）→ 命中章节级 Collection
- [ ] 对比问题（"这几篇论文区别？"）→ 命中论文级 Collection
- [ ] 支持 metadata 过滤（按 paper_id、section 过滤）
- [ ] Top-K 默认 5，可配置

---

## 模块 6：缓存与 Token 管理

### 任务 6.1：Redis 搜索缓存

**文件**：`agent/app/services/cache.py`

**功能描述**：
缓存 MCP 工具的搜索结果，相同 query 在 TTL 内直接返回缓存。

**验收标准**：
- [ ] 缓存 key 格式：`search:{tool_name}:{md5(query_params)}`
- [ ] TTL 默认 1 小时
- [ ] 命中缓存时不调用外部 API
- [ ] 支持手动清除缓存

### 任务 6.2：Token 预算控制

**文件**：`agent/app/services/token_budget.py`

**功能描述**：
控制单次研究任务的 Token 消耗，超出预算时压缩上下文。

**验收标准**：
- [ ] 每次 LLM 调用后累计 Token 使用量
- [ ] 接近预算（80%）时触发上下文压缩：保留系统提示 + 最近 3 轮 + 关键结果摘要
- [ ] 超出预算时停止 Agent 迭代，返回已有结果
- [ ] 预算默认 50000 tokens，可配置

---

## 模块 7：Vue3 前端

### 任务 7.1：项目初始化

**功能描述**：
使用 Vite 创建 Vue3 + TypeScript 项目，配置 Element Plus、Pinia、Vue Router、SCSS。

**验收标准**：
- [ ] `npm run dev` 启动成功
- [ ] Element Plus 组件可正常使用
- [ ] TypeScript 编译无错误
- [ ] 路由配置：`/` 聊天页、`/history` 历史页

### 任务 7.2：WebSocket 通信层

**文件**：`web/src/composables/useWebSocket.ts`, `web/src/api/chat.ts`

**功能描述**：
实现 WebSocket 连接管理，处理流式消息。

**验收标准**：
- [ ] 连接 `ws://gateway:8080/ws?session_id=xxx` 成功
- [ ] 发送消息后接收流式 token 事件
- [ ] 断线自动重连（3 次，指数退避）
- [ ] 组件卸载时自动断开连接
- [ ] 连接状态可观测（isConnected ref）

### 任务 7.3：聊天界面

**文件**：`web/src/components/ChatPanel/`, `web/src/views/ChatView.vue`

**功能描述**：
实现聊天主界面，支持消息发送、流式显示、Agent 状态指示。

**验收标准**：
- [ ] 消息气泡区分用户/助手
- [ ] 助手消息支持 Markdown 渲染（表格、代码块、列表）
- [ ] 流式输出：逐字显示，有光标闪烁效果
- [ ] Agent 状态指示：消息上方显示 "正在检索 ArXiv..." 等状态
- [ ] 输入框支持 Enter 发送、Shift+Enter 换行
- [ ] 消息列表自动滚动到底部

### 任务 7.4：PDF 上传

**文件**：`web/src/components/ChatPanel/InputBar.vue`

**功能描述**：
在输入栏集成 PDF 上传功能。

**验收标准**：
- [ ] 支持点击上传和拖拽上传
- [ ] 仅接受 PDF 格式，其他格式提示错误
- [ ] 上传中显示进度条
- [ ] 上传成功后在输入栏显示文件标签（可删除）
- [ ] 文件大小限制 20MB，超出前端提示

### 任务 7.5：报告展示组件

**文件**：`web/src/components/ReportView/`

**功能描述**：
展示 Synthesis Agent 生成的结构化报告。

**验收标准**：
- [ ] 对比表格：Element Plus Table 组件渲染，支持列排序
- [ ] 文献综述：Markdown 渲染，引用标注可点击跳转到论文详情
- [ ] 时间线：可视化展示研究脉络（Element Plus Timeline 组件）
- [ ] 报告支持复制为 Markdown 文本

### 任务 7.6：会话管理

**文件**：`web/src/components/Sidebar/`, `web/src/stores/session.ts`

**功能描述**：
侧边栏展示会话列表，支持新建、切换、删除会话。

**验收标准**：
- [ ] 显示会话列表（标题 + 创建时间 + 最后消息预览）
- [ ] 点击切换会话，加载历史消息
- [ ] 新建会话按钮
- [ ] 删除会话（二次确认）
- [ ] 当前会话高亮

---

## 模块 8：部署

### 任务 8.1：Docker 化

**文件**：`gateway/Dockerfile`, `agent/Dockerfile`, `web/Dockerfile`, `docker-compose.yml`

**验收标准**：
- [ ] 每个服务有独立 Dockerfile，构建成功
- [ ] `docker-compose up` 一键启动所有服务
- [ ] 服务间网络互通（gateway → agent gRPC, gateway → redis, agent → chroma）
- [ ] 环境变量通过 `.env` 文件注入
- [ ] 前端 nginx 配置反向代理 `/api` → gateway
