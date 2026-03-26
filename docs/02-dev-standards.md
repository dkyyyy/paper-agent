# Paper Agent — AI 开发规范文档

## 1. 项目结构规范

### 1.1 仓库结构（Monorepo）

```
paper-agent/
├── gateway/          # Go 后端网关
├── agent/            # Python Agent 服务
├── web/              # Vue3 前端
├── proto/            # gRPC Proto 定义（共享）
├── docs/             # 项目文档
├── docker-compose.yml
├── Makefile
└── README.md
```

### 1.2 共享 Proto 定义

`proto/` 目录为 Go 和 Python 共享的 gRPC 接口定义，修改后需同时重新生成两端代码。

---

## 2. Go 后端开发规范

### 2.1 项目规范
- Go 版本：1.22+
- Web 框架：Gin
- 配置管理：Viper（YAML 配置文件）
- Redis 客户端：go-redis/v9
- gRPC：google.golang.org/grpc
- 日志：slog（标准库）
- 错误处理：统一错误码 + 错误包装

### 2.2 目录约定
- `cmd/`：程序入口，只做依赖注入和启动
- `internal/`：业务代码，不对外暴露
- `internal/handler/`：HTTP/WebSocket 处理器，只做参数校验和响应格式化
- `internal/service/`：业务逻辑层
- `internal/model/`：数据模型定义

### 2.3 编码规范
- 所有导出函数必须有注释
- 错误不要丢弃，必须处理或向上传递
- Context 必须作为第一个参数传递
- 使用 `slog` 结构化日志，不用 `fmt.Println`

### 2.4 API 响应格式

```go
// 统一响应结构
type Response struct {
    Code    int         `json:"code"`    // 0=成功，非0=错误码
    Message string      `json:"message"`
    Data    interface{} `json:"data,omitempty"`
}
```

### 2.5 WebSocket 消息格式

```json
// 客户端 → 服务端
{
  "type": "chat",
  "session_id": "uuid",
  "content": "调研 RAG 优化最新进展",
  "attachments": ["file_id_1"]
}

// 服务端 → 客户端（流式）
{
  "type": "stream",
  "session_id": "uuid",
  "event": "token",        // token | agent_status | done | error
  "data": {
    "content": "根据检索结果...",
    "agent": "search_agent",
    "step": "searching_arxiv"
  }
}
```

---

## 3. Python Agent 开发规范

### 3.1 项目规范
- Python 版本：3.11+
- 包管理：pip + requirements.txt（或 poetry）
- Agent 框架：LangGraph 0.2+ / LangChain 0.3+
- gRPC：grpcio + grpcio-tools
- 向量库：chromadb
- PDF 解析：PyMuPDF (fitz)
- 代码格式化：black + isort
- 类型检查：mypy（建议）

### 3.2 Agent 开发模板

每个 Agent 必须遵循以下结构：

```python
"""
Agent: [Agent 名称]
职责: [一句话描述]
绑定工具: [MCP 工具列表]
"""

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, END

# 1. 定义 Agent State
class SearchAgentState(TypedDict):
    messages: list          # 消息历史
    papers: list[Paper]     # 检索到的论文
    query_history: list[str] # 已执行的查询
    iteration: int          # 当前迭代轮次
    max_iterations: int     # 最大迭代次数
    status: str             # pending | running | completed | failed

# 2. 定义节点函数（每个节点职责单一）
def plan_search(state: SearchAgentState) -> dict:
    """规划搜索策略"""
    ...

def execute_search(state: SearchAgentState) -> dict:
    """执行搜索"""
    ...

def evaluate_results(state: SearchAgentState) -> dict:
    """评估结果质量"""
    ...

# 3. 定义条件边
def should_continue(state: SearchAgentState) -> str:
    """判断是否需要继续搜索"""
    if state["iteration"] >= state["max_iterations"]:
        return "done"
    if len(state["papers"]) >= 15:
        return "done"
    return "continue"

# 4. 构建 Graph
def build_search_graph() -> StateGraph:
    graph = StateGraph(SearchAgentState)
    graph.add_node("plan", plan_search)
    graph.add_node("search", execute_search)
    graph.add_node("evaluate", evaluate_results)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "evaluate")
    graph.add_conditional_edges("evaluate", should_continue, {
        "continue": "plan",
        "done": END
    })
    return graph.compile()
```

### 3.3 MCP Server 开发模板

每个 MCP Server 必须遵循以下结构：

```python
"""
MCP Server: [服务名称]
提供工具:
  - tool_name_1: [描述]
  - tool_name_2: [描述]
外部依赖: [API 名称 + 文档链接]
"""

from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("arxiv-server")

# 1. 工具定义：必须有清晰的 description 和 inputSchema
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="arxiv_search",
            description="Search academic papers on ArXiv by keywords. Returns title, abstract, authors, date, and ArXiv ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query keywords, e.g. 'retrieval augmented generation'"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (1-50)",
                        "default": 20
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["relevance", "lastUpdatedDate", "submittedDate"],
                        "default": "relevance"
                    }
                },
                "required": ["query"]
            }
        )
    ]

# 2. 工具实现：必须有错误处理和超时控制
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "arxiv_search":
        try:
            results = await search_arxiv(
                query=arguments["query"],
                max_results=arguments.get("max_results", 20),
                sort_by=arguments.get("sort_by", "relevance")
            )
            return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]
```

### 3.4 Prompt 编写规范

所有 Prompt 集中在 `prompts/` 目录，遵循以下规范：

```python
"""
Prompt: [Agent 名称] System Prompt
版本: v1.0
最后更新: 2025-01-15
"""

SUPERVISOR_SYSTEM_PROMPT = """你是一个学术研究助手的调度中心。

## 角色
你负责理解用户的研究需求，将其拆解为子任务，并分配给专业的子 Agent 执行。

## 可用子 Agent
1. search_agent: 文献检索，支持 ArXiv、Semantic Scholar、DBLP 多源搜索
2. analysis_agent: 论文深度分析，提取研究问题、方法、数据集、指标、结果
3. synthesis_agent: 跨论文综合分析，生成对比报告和文献综述

## 任务拆解规则
- 文献调研类：search_agent → analysis_agent → synthesis_agent
- 论文精读类：analysis_agent（直接分析上传的 PDF）
- 方法对比类：search_agent → analysis_agent（并行） → synthesis_agent
- Gap 发现类：基于已有分析结果 → synthesis_agent

## 输出格式
以 JSON 格式输出任务计划：
{
  "intent": "文献调研 | 论文精读 | 方法对比 | Gap发现",
  "plan": [
    {"agent": "search_agent", "task": "...", "params": {...}},
    {"agent": "analysis_agent", "task": "...", "depends_on": [0]}
  ]
}
"""
```

规则：
- 每个 Prompt 必须有明确的角色定义、能力边界、输出格式
- 使用中文编写（面向国产模型优化）
- Prompt 中不要硬编码具体数据，用占位符 `{variable}` 表示动态内容
- 版本化管理，修改时更新版本号

### 3.5 RAG 管线规范

#### 分块策略
```python
# 论文分块配置
CHUNK_CONFIG = {
    "paragraph": {      # L1 段落级
        "chunk_size": 512,
        "chunk_overlap": 50,
        "separator": "\n\n"
    },
    "section": {        # L2 章节级
        "chunk_size": 2048,
        "chunk_overlap": 200,
        "separator": "## "  # 按章节标题分割
    },
    "paper": {          # L3 论文级
        "strategy": "llm_summary",  # 用 LLM 生成论文摘要
        "max_tokens": 500
    }
}
```

#### 向量化规范
- Embedding 模型：使用通义千问 text-embedding-v3 或 BGE 系列
- Collection 命名：`papers_{level}`（如 `papers_paragraph`、`papers_section`）
- Metadata 必须包含：`paper_id`、`section`、`level`、`chunk_index`

---

## 4. Vue3 前端开发规范

### 4.1 技术栈
- Vue 3.4+ (Composition API + `<script setup>`)
- TypeScript 5+
- Vite 5+
- Pinia（状态管理）
- Vue Router 4
- Element Plus（组件库）
- markdown-it（Markdown 渲染）
- 样式：SCSS + CSS Variables

### 4.2 编码规范
- 组件使用 `<script setup lang="ts">` 语法
- 组件命名：PascalCase（`ChatPanel.vue`）
- Composable 命名：`use` 前缀（`useWebSocket.ts`）
- Store 命名：与业务对应（`chat.ts`、`session.ts`）
- API 请求统一封装在 `api/` 目录
- 不使用 `any` 类型，所有接口数据定义 TypeScript 类型

### 4.3 WebSocket 管理

```typescript
// composables/useWebSocket.ts
export function useWebSocket(sessionId: string) {
  const ws = ref<WebSocket | null>(null)
  const isConnected = ref(false)

  function connect() {
    ws.value = new WebSocket(`ws://${API_HOST}/ws/${sessionId}`)
    ws.value.onmessage = (event) => {
      const msg: StreamMessage = JSON.parse(event.data)
      handleMessage(msg)
    }
  }

  function handleMessage(msg: StreamMessage) {
    switch (msg.event) {
      case 'token':       // 追加文本到当前消息
      case 'agent_status': // 更新 Agent 执行状态指示器
      case 'done':        // 标记消息完成
      case 'error':       // 显示错误提示
    }
  }

  return { connect, disconnect, isConnected, sendMessage }
}
```

### 4.4 关键 UI 交互

| 功能 | 实现方式 |
|------|---------|
| 流式输出 | WebSocket 接收 token 事件，逐字追加到消息气泡 |
| Agent 状态 | 消息气泡上方显示当前执行的 Agent 和步骤（如 "正在检索 ArXiv..."） |
| PDF 上传 | Element Plus Upload 组件，拖拽上传，上传后显示文件名 |
| Markdown 渲染 | markdown-it 渲染，支持表格、代码块、LaTeX 公式 |
| 对比表格 | 独立 ComparisonTable 组件，支持排序和高亮 |
| 会话切换 | 侧边栏会话列表，点击切换，自动恢复历史消息 |

---

## 5. gRPC 接口规范

### 5.1 Proto 文件管理

```
proto/
└── agent/
    └── v1/
        └── agent.proto
```

修改 proto 后执行：
```bash
# 生成 Go 代码
protoc --go_out=gateway --go-grpc_out=gateway proto/agent/v1/agent.proto

# 生成 Python 代码
python -m grpc_tools.protoc -Iproto --python_out=agent/app --grpc_python_out=agent/app proto/agent/v1/agent.proto
```

### 5.2 流式通信约定

Go → Python 使用 gRPC Server Streaming：
- 请求：一次性发送用户消息 + 会话上下文
- 响应：流式返回 Agent 执行过程中的每个事件（token、状态变更、最终结果）

---

## 6. 配置管理规范

### 6.1 环境变量

```bash
# .env.example
# LLM
LLM_PROVIDER=dashscope          # dashscope | zhipu
LLM_API_KEY=sk-xxx
LLM_MODEL=qwen-plus             # 或 glm-4

# Embedding
EMBEDDING_MODEL=text-embedding-v3

# Redis
REDIS_URL=redis://localhost:6379/0

# Chroma
CHROMA_HOST=localhost
CHROMA_PORT=8000

# gRPC
GRPC_AGENT_ADDR=localhost:50051

# Go Gateway
GATEWAY_PORT=8080
```

### 6.2 配置优先级
环境变量 > 配置文件 > 默认值

---

## 7. 测试规范

### 7.1 Go 测试
- 单元测试：`*_test.go`，覆盖 handler 和 service 层
- 集成测试：使用 testcontainers-go 启动 Redis 容器

### 7.2 Python 测试
- 单元测试：pytest，mock LLM 调用
- Agent 测试：使用 LangGraph 的 `graph.invoke()` 端到端测试
- MCP 工具测试：mock 外部 API 响应，验证工具输入输出格式

### 7.3 前端测试
- 组件测试：Vitest + Vue Test Utils
- 重点测试 WebSocket 消息处理和 Markdown 渲染

---

## 8. Git 规范

### 8.1 分支策略
- `main`：稳定版本
- `dev`：开发分支
- `feat/xxx`：功能分支
- `fix/xxx`：修复分支

### 8.2 Commit Message
```
<type>(<scope>): <subject>

type: feat | fix | refactor | docs | test | chore
scope: gateway | agent | web | proto | docs
```

示例：
```
feat(agent): add arxiv mcp server with search tool
fix(gateway): fix websocket connection leak on session timeout
feat(web): implement streaming message display with markdown
```
