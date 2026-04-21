# 未实现功能清单

> 本文档记录架构设计中存在但代码中尚未实现的功能，供新窗口认领实现，主窗口负责验收。
>
> **已完成（2026-04-20）：** #2 PostgreSQL 持久化层 ✅
>
> **已完成（2026-04-14）：** #3 Analysis 并行化 ✅ | #4 Quality Check 规则前置 ✅ | #5 RAG 接入 paper_qa ✅ | #6 Session List SCAN 替换 ✅

---

## 1. MCP Server 层（完全缺失）

**架构设计位置：** `agent/app/mcp_servers/`

**现状：** 目录不存在。`search_agent.py` 直接用 `urllib` 调用 ArXiv 和 Semantic Scholar API，没有 MCP 协议封装。

**需要实现：**

| 文件 | 功能 |
|------|------|
| `mcp_servers/arxiv_server.py` | ArXiv MCP Server，工具：`arxiv_search(query, max_results, year_from)` |
| `mcp_servers/semantic_scholar.py` | S2 MCP Server，工具：`s2_search(query, max_results, year_from)` |
| `mcp_servers/pdf_parser.py` | PDF 解析 MCP Server，工具：`parse_pdf(file_path)` → 返回结构化文本 |

**MCP Server 最小实现模板：**
```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

app = Server("arxiv-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(name="arxiv_search", description="...", inputSchema={...})]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "arxiv_search":
        results = _do_search(arguments["query"])
        return [TextContent(type="text", text=json.dumps(results))]
```

**验收标准：**
- `arxiv_server.py` 能独立启动（`python -m app.mcp_servers.arxiv_server`）
- 通过 MCP Inspector 能看到工具列表
- `search_agent.py` 改为通过 MCP Client 调用，而不是直接调 urllib

---

## 2. ✅ PostgreSQL 持久化层（已完成）

**架构设计位置：** `docs/01-architecture.md` 5.2 节

**完成情况：**
- `agent/app/services/db.py` 已用 `psycopg2` 实现 `save_paper/get_paper/save_message/list_sessions`
- `gateway/internal/service/session.go` 已改为 PostgreSQL 持久化 + Redis 1h 热缓存
- `docker/init.sql` 已建 `papers` / `sessions` / `messages` / `research_projects` / `uploaded_files` 五张表
- `docker-compose.yml` 已挂载 `docker/init.sql`，容器初始化时自动建表

**验收结果：**
- `docker-compose.yml` 已声明 PostgreSQL 容器并挂载 `docker/init.sql`
- 会话读取逻辑已实现 Redis miss 后回源 PostgreSQL 恢复
- `paper_store.py` 的元数据已写入 `papers` 表，不再写本地 JSON

---

## 3. ✅ Analysis 并行化（已完成）

**问题位置：** `agent/app/agents/supervisor.py:453` 和 `agent/app/agents/comparison_agent.py:441`

**现状：** 两处都是 for 循环串行分析每篇论文，10 篇论文 × 2次 LLM 调用 ≈ 2 分钟。

**需要实现：** 在 `supervisor.py` 的 `_dispatch_single_agent` analysis 分支中：

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _analyze_papers_parallel(papers, max_workers=4):
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_paper = {
            executor.submit(
                run_analysis,
                paper_id=p.get("paper_id", ""),
                paper_title=p.get("title", "Untitled"),
                paper_content=p.get("abstract", ""),
                persist_to_vectordb=False,
            ): p
            for p in papers
            if (p.get("abstract") or "").strip()
        }
        for future in as_completed(future_to_paper, timeout=60):
            paper = future_to_paper[future]
            try:
                result = future.result()
                results.append({**paper, "extracted_info": result.get("extracted_info", {}), ...})
            except Exception as exc:
                logger.warning("Paper analysis failed: %s", exc)
    return results
```

同样的改动应用到 `comparison_agent.py` 的 `_analyze_papers` 函数。

**验收标准：**
- 10 篇论文分析耗时 < 40 秒（原来约 120 秒）
- 结果顺序不影响正确性（已用 dict 收集，不依赖顺序）

---

## 4. ✅ Quality Check 规则前置（已完成）

**问题位置：** `agent/app/agents/supervisor.py:520`

**现状：** 完全依赖 LLM 打分，无规则兜底，容易出现：
- LLM 对明显不足（只检到 1 篇论文）的结果打 8 分
- 每次 quality_check 都耗费 Token

**需要实现：** 在 LLM 评分前加规则检查：

```python
def _rule_check(state: SupervisorState, candidate_output: str) -> str | None:
    """返回 None 表示通过，返回字符串表示失败原因。"""
    papers = state.get("analysis_results", [])
    if len(papers) < 2:
        return f"论文数量不足（{len(papers)} 篇，要求 ≥2）"
    if len(candidate_output) < 300:
        return f"输出过短（{len(candidate_output)} 字符，要求 ≥300）"
    cited = sum(1 for p in papers[:5] if (p.get("title") or "") in candidate_output)
    if cited == 0:
        return "输出中未引用任何论文标题"
    return None
```

**验收标准：**
- 单元测试：论文数 < 2 时 quality_check 直接触发 retry，不调用 LLM
- 规则通过后才调用 LLM 打分

---

## 5. ✅ RAG 检索接入 paper_qa（已完成）

**问题位置：** `agent/app/rag/retriever.py` 实现了，但 `paper_qa` 意图走的是 search→analysis→synthesis 流程，没有使用向量检索。

**现状：** 用户上传 PDF 后问"第三节的方法是什么"，走的是全文截断 → LLM 分析，而不是向量检索 → 精准定位段落。

**需要实现：** 在 `synthesis_agent.py` 的 `paper_qa` 任务类型中，优先用 `retriever.retrieve()` 找到相关段落，再生成回答：

```python
from app.rag.retriever import retrieve

if task_type == "paper_qa" and paper_ids:
    # 向量检索相关段落
    context_chunks = []
    for pid in paper_ids:
        chunks = retrieve(question=user_query, paper_id=pid, top_k=5)
        context_chunks.extend(chunks)
    # 用检索到的段落回答，而不是全文摘要
    ...
```

**验收标准：**
- 上传 PDF 后提问，`events` 中出现 `"Retrieving from Chroma"` 相关日志
- 回答中引用了具体段落内容（而非笼统摘要）

---

## 6. ✅ Session List 性能（已完成）

**问题位置：** `gateway/internal/service/session.go:122`

**现状：**
```go
keys, err := s.rdb.Keys(ctx, sessionKeyPrefix+"*").Result()
```
`KEYS` 命令在生产环境会阻塞 Redis，万条 key 时延迟明显。

**需要实现：** 改用 `SCAN` 迭代或维护一个独立的会话 ID Set：
```go
// 方案 A：SCAN 替代 KEYS
var cursor uint64
for {
    keys, cursor, err = s.rdb.Scan(ctx, cursor, sessionKeyPrefix+"*", 100).Result()
    ...
    if cursor == 0 { break }
}

// 方案 B（推荐）：写入时同时维护 Set
s.rdb.SAdd(ctx, "session:index", sess.ID)
// List 时直接 SMEMBERS session:index
```

**验收标准：**
- `List` 函数不再出现 `KEYS` 命令（可用 Redis Monitor 验证）
- 1000 个 session 下 List 响应时间 < 100ms
