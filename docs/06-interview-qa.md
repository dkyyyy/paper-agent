# 面试问题库 & 知识点速查

> 面向 Agent 开发岗位。每道题都附：**标准答案要点** + **对应代码位置** + **涉及知识点**。

---

## 一、LangGraph & Agent 编排

### Q1：为什么选 LangGraph？对比 LCEL、AutoGen、手写 if-else 的区别？

**答案要点：**
- **手写 if-else**：状态散落在函数参数里，条件分支超过 3 层就不可维护；没有内置的重试/回滚机制。
- **LangChain LCEL**：链式调用适合线性 pipeline，无法表达条件分支和循环（如 quality_check → retry）。
- **AutoGen**：多 Agent 对话框架，Agent 之间通过消息传递协作，适合开放式对话，但状态管理弱，难以精确控制执行流。
- **LangGraph**：显式 StateGraph，状态集中在 TypedDict，节点函数只做状态变换，边表达控制流。核心优势：**有向图 + 条件边 + 持久化 Checkpoint**，天然支持 human-in-the-loop 和断点续跑。

**代码位置：** `agent/app/agents/supervisor.py:623` — `build_supervisor_graph()`

**涉及知识点：**
- LangGraph StateGraph / TypedDict State
- 条件边 `add_conditional_edges`
- 节点函数签名：`(state: S) -> dict` 返回 partial update

---

### Q2：Supervisor 的状态机有哪些节点？数据怎么流转？

**答案要点：**

```
intent_recognition
    ├── chitchat → END
    ├── method_comparison → run_comparison → END
    └── 其他意图 → dispatch_agents → quality_check
                                          ├── passed → END
                                          └── retry → dispatch_agents（循环）
```

状态流转关键字段：
- `intent_recognition` 写入：`intent`, `topic`, `research_plan`, `sub_questions`
- `dispatch_agents` 写入：`search_results`, `analysis_results`, `synthesis_output`
- `quality_check` 写入：`final_output` 或 `quality_feedback`（重试时清空中间结果）

**代码位置：** `supervisor.py:613` — `after_intent()`, `should_retry()`

**涉及知识点：**
- LangGraph 的 partial state update（节点只返回要更新的字段）
- 条件路由函数 `Literal["a", "b", "c"]` 返回类型
- 状态隔离：子 Agent 通过返回值更新 SupervisorState，不直接修改

---

### Q3：dispatch_agents 为什么是串行的？并行化怎么做？

**答案要点：**
- 当前串行原因：Search → Analysis → Synthesis 有数据依赖（Analysis 需要 Search 的结果），无法跨 Agent 并行。
- **可以并行的地方**：Analysis 内部，每篇论文的分析是独立的，可以用 `ThreadPoolExecutor` 并行。
- **LangGraph 的 Send API**：可以用 `Send` 将多个并行子任务分发到同一节点，结果汇聚后继续。

```python
# LangGraph Send 并行示例
from langgraph.constants import Send

def dispatch_parallel(state):
    return [Send("analyze_paper", {"paper": p}) for p in state["papers"]]
```

- **实际做的**：用 `ThreadPoolExecutor(max_workers=4)` 并行分析论文，耗时从 ~120s → ~30s。

**代码位置：** `supervisor.py:278` — `dispatch_agents()`（当前串行实现）

**涉及知识点：**
- Python `concurrent.futures.ThreadPoolExecutor`
- LangGraph `Send` API（Map-Reduce 模式）
- 线程安全：LLM 客户端是否线程安全（通常是）

---

### Q4：quality_check 的 LLM 自评可靠性如何保证？

**答案要点：**
- 纯 LLM 自评的问题：倾向于给自己高分（self-serving bias），对明显不足的输出也可能通过。
- 改进方案：**规则检查前置 + LLM 语义检查兜底**。
  - 规则层（确定性）：论文数量 ≥ 2、输出长度 ≥ 300 字符、至少引用 1 篇论文标题
  - LLM 层（语义）：输出是否回答了用户问题、逻辑是否连贯
- `quality_feedback` 传给 `search_agent`，下一轮搜索时 LLM 根据 feedback 重新规划关键词（`supervisor.py:109` — feedback replanning）

**代码位置：** `supervisor.py:520` — `quality_check()`

**涉及知识点：**
- LLM 评估的可靠性与幻觉问题
- Self-consistency / Constitutional AI 思想
- 有限重试（max_iterations）防止无限循环

---

## 二、RAG 管线

### Q5：三个 Chroma Collection 的用途？检索时怎么决定查哪一层？

**答案要点：**

| Collection | 粒度 | 适用问题 |
|-----------|------|---------|
| `papers_paragraph` | 段落级（~200 字） | "第3节的损失函数是什么" / 具体数值、公式 |
| `papers_section` | 章节级（~800 字） | "这篇论文的方法是什么" / 模型架构 |
| `papers_summary` | 全文摘要（LLM 生成） | "对比这5篇论文的方法" / 跨论文综合 |

检索粒度决策：
1. **LLM 判断**：`LEVEL_DETECTION_PROMPT` 让 LLM 输出 `paragraph/section/paper`
2. **启发式回退**：LLM 失败时，关键词规则兜底（含 "loss/公式/细节" → paragraph，含 "对比/综述" → paper）

**代码位置：** `agent/app/rag/retriever.py:67` — `detect_level()`

**涉及知识点：**
- Chroma `HttpClient` + `collection.query(query_embeddings=[...])`
- 向量相似度：cosine distance → score = 1.0 - distance
- Hierarchical RAG / Multi-granularity Retrieval

---

### Q6：论文怎么分块的？有没有 Rerank？

**答案要点：**
- **段落分块**（`chunk_paragraph`）：按 `\n\n` 双换行分段，过滤 < 100 字的碎片，保留 `section` 字段标记所属章节。
- **章节分块**（`chunk_section`）：按一级标题 `## / # ` 切割，每个章节作为一个 chunk。
- **去重**：`indexer.py` 用 MD5 hash 检查是否已入库，避免重复向量化。
- **Rerank**：当前没有实现跨 chunk 的 Rerank（如 Cohere Rerank / BGE Reranker）。可以加：`retriever.py` 的 `retrieve()` 返回后，用 cross-encoder 对 top-k 重排序。

**代码位置：** `agent/app/rag/chunker.py`, `agent/app/rag/indexer.py`

**涉及知识点：**
- Chunking 策略：fixed-size vs semantic vs hierarchical
- Embedding 模型选型（`embeddings.py` 中的配置）
- Reranker：bi-encoder（检索用）vs cross-encoder（精排用）

---

### Q7：为什么 paper_qa 没有用向量检索？

**答案要点（诚实回答）：**
- 当前实现：`paper_qa` 意图走 search→analysis→synthesis 流程，`analysis_agent` 只是截断全文前 12000 字交给 LLM。
- 问题：用户问"第3节的实验用了什么数据集"，全文摘要模式容易遗漏细节。
- 应该的做法：先用 `retriever.retrieve(question, level="paragraph", paper_id=pid)` 定位相关段落，再用 LLM 基于段落回答。
- 这是一个**已知缺陷**，向量库已建好，接入点在 `synthesis_agent` 的 `paper_qa` 分支。

**代码位置：** `agent/app/rag/retriever.py:89` — `retrieve()`（已实现但未接入）

**涉及知识点：**
- RAG vs long-context LLM 的权衡
- Retrieval-Augmented Generation 与 full-document analysis 的适用场景

---

## 三、系统架构

### Q8：Go + Python 双服务为什么用 gRPC 而不是 HTTP？

**答案要点：**
- **Server Streaming**：Agent 执行过程中产生的 events（"正在搜索 ArXiv..."）需要实时推送给前端，gRPC Server Streaming 天然支持，HTTP 需要额外实现 SSE。
- **强类型**：Proto 定义的 `AgentRequest/AgentResponse` 强制两端接口一致，避免 JSON 字段名拼写错误。
- **序列化效率**：Protobuf 二进制序列化比 JSON 更快，对高频的 streaming chunk 有优势。
- **服务发现**：gRPC 与 Kubernetes/Consul 生态整合更好（虽然本项目是 docker-compose）。

**代码位置：** `agent/app/grpc_server.py`, `gateway/internal/service/agent_client.go`

**涉及知识点：**
- gRPC 四种模式：Unary / Server Streaming / Client Streaming / Bidirectional
- Protobuf IDL，生成 Python stub 和 Go stub
- gRPC status codes vs HTTP status codes

---

### Q9：Redis 和 PostgreSQL 的分层存储设计是什么思路？

**答案要点：**

```
读热数据 → Redis (TTL 1h)
写持久化 → PostgreSQL
```

- **Redis 存什么**：活跃会话上下文（Agent 高频读写）、搜索结果缓存（避免重复调外部 API）、Token 预算计数器
- **PostgreSQL 存什么**：历史消息（用户需要回溯）、论文元数据（需要按年份/作者查询）、五元组提取结果（JSONB 支持半结构化查询）
- **为什么不全用 Redis**：TTL 过期后数据消失，论文元数据和会话历史需要永久保存
- **为什么不全用 PostgreSQL**：会话上下文在 Agent 执行期间高频读写，关系型数据库的锁和事务开销不必要

**当前实现状态**：PostgreSQL 层尚未实现，仅有 Redis 会话存储 + 本地文件系统 paper_store。

**涉及知识点：**
- Redis 数据类型：Hash（会话上下文）/ String（搜索缓存）/ Counter（Token 计数）
- PostgreSQL JSONB + GIN 索引（半结构化数据查询）
- 缓存穿透 / 缓存击穿防护（搜索缓存的 MD5 key 设计）

---

### Q10：Session List 为什么用 SCAN 而不是 KEYS？

**答案要点：**
- `KEYS pattern` 是 O(N) 全量扫描，执行期间**阻塞 Redis 单线程**，在生产环境中可能导致其他请求超时。
- `SCAN cursor pattern count` 是增量迭代，每次返回少量结果，不阻塞。
- 更好的方案：写入时同时 `SADD session:index {session_id}`，List 时 `SMEMBERS session:index`，O(N) 但不阻塞。

**当前问题位置：** `gateway/internal/service/session.go:122` — `Keys()` 调用

**涉及知识点：**
- Redis 单线程模型与命令复杂度
- `KEYS` vs `SCAN` vs 维护索引 Set 三种方案对比
- Redis 生产环境最佳实践

---

## 四、工程细节 & 踩坑

### Q11：LLM 返回的 JSON 解析为什么要特殊处理？

**答案要点：**
LLM 经常在 JSON 外面包一层 markdown 代码块：
```
```json
{"intent": "literature_review"}
```
```
直接 `json.loads(response)` 会报错。

解决方案：`_extract_json_payload()` 先剥离 ` ```json ` / ` ``` ` 包裹，再解析。失败时 fallback 到预设结构，而不是抛异常崩溃。

**代码位置：** `supervisor.py:70` — `_extract_json_payload()`（每个 Agent 都有相同的工具函数，是复制的，可以抽出到 `utils.py`）

**涉及知识点：**
- LLM 输出不可靠性：指令跟随失败、格式幻觉
- Defensive parsing 模式
- 结构化输出替代方案：`response_format={"type": "json_object"}`（OpenAI）/ LangChain `JsonOutputParser`

---

### Q12：Planner 失败时为什么用降级而不是报错？

**答案要点：**
- Planner 是在 Supervisor `intent_recognition` 节点内部调用的，失败不应该中断整个 Agent 流程。
- 降级逻辑：Planner 失败 → `logger.warning` + `events` 记录 → 继续执行，用 `fallback_topic` 和默认搜索策略。
- 原则：**辅助优化路径失败，不影响主路径**。Planner 的作用是把用户查询拆成子问题、提高搜索质量；没有它，系统仍然可以用原始 query 直接搜索。

**代码位置：** `supervisor.py:241` — Planner 调用的 try-except 块

**涉及知识点：**
- 容错设计：Fail-fast vs Graceful degradation
- LangGraph 中的错误处理：节点内 try-except vs 全局 error handler
- 可观测性：`events` 列表记录执行过程，便于调试

---

### Q13：Token 预算压缩是什么场景下触发的？

**答案要点：**
- 触发条件：对话轮数超过 `config.token_keep_recent_turns * 2`，且当前 token 使用量超过阈值（`budget.should_compress`）。
- 压缩策略：保留最近 N 轮消息（防止上下文截断导致回答质量下降），早期消息丢弃。
- 为什么需要：LLM 上下文窗口有限（通义千问/GLM 一般 8k-32k），长对话的历史消息会占满 context，导致 LLM 看不到最新问题。

**代码位置：** `supervisor.py:156` — `_build_supervisor_messages()`, `services/token_budget.py`

**涉及知识点：**
- LLM Context Window 限制
- Sliding window / Summarization 两种压缩策略
- Token 计数（不同 tokenizer 的差异）

---

## 五、搜索 Agent 细节

### Q14：多源搜索的去重逻辑是什么？

**答案要点：**
三层去重，依次执行：
1. **DOI 精确匹配**：同一篇论文在 ArXiv 和 S2 都有，DOI 相同直接去重。
2. **标题 MD5 hash**：小写 + MD5，完全相同的标题去重。
3. **标题模糊匹配**：`SequenceMatcher` 计算编辑距离，相似度 > 0.85 认为是同一篇（防止"RAG Survey"vs"A RAG Survey"这类微小差异）。

**排序分数（多维度加权）：**
```
score = 引用数得分×0.4 + 时效性得分×0.4 + 有摘要×0.2
```

**代码位置：** `search_agent.py:390` — `deduplicate_and_rank()`

**涉及知识点：**
- Python `difflib.SequenceMatcher`
- 多源数据融合的去重策略
- 相关性排序：citation count + recency + completeness

---

### Q15：搜索迭代扩展是怎么做的？

**答案要点：**
- 初始搜索不满足 `target_count` 时，`should_continue` 返回 `"continue"`，LangGraph 循环回 `plan_search`。
- 第二轮 `plan_search` 用 `QUERY_EXPANSION_PROMPT`：告诉 LLM "已用了哪些关键词，还差几篇，生成新的查询词"。
- 最多 `max_iterations` 轮（默认 1，可配置），防止无限扩展浪费 API 额度。
- `feedback` 字段：quality_check 失败时传入反馈，第一轮 `plan_search` 用 feedback 重新规划，而不是盲目扩展。

**代码位置：** `search_agent.py:446` — `should_continue()`, `search_agent.py:102` — `plan_search()`

**涉及知识点：**
- LangGraph 循环（Conditional Edge 返回同一节点）
- 自适应搜索 / Query Expansion
- Agentic loop 的终止条件设计

---

## 六、速查表：知识点 → 对应代码

| 知识点 | 代码位置 |
|--------|---------|
| LangGraph StateGraph + TypedDict | `supervisor.py:28`, `search_agent.py:48`, `analysis_agent.py:18` |
| 条件边路由 | `supervisor.py:613`, `search_agent.py:446` |
| LangGraph Send（并行，待实现）| — |
| gRPC Server Streaming | `grpc_server.py`, `proto/agent.proto` |
| Redis 会话管理 | `gateway/internal/service/session.go` |
| Chroma 向量存储与检索 | `rag/indexer.py`, `rag/retriever.py` |
| 分层 RAG（多粒度） | `rag/chunker.py`, `rag/retriever.py:16` |
| MD5 去重 | `rag/indexer.py:compute_file_hash()` |
| Token 预算压缩 | `services/token_budget.py`, `supervisor.py:156` |
| LLM JSON 解析容错 | `supervisor.py:70` — `_extract_json_payload()` |
| 多源搜索去重排序 | `search_agent.py:390` — `deduplicate_and_rank()` |
| 搜索结果 Redis 缓存 | `services/cache.py`, `search_agent.py:255` |
| 质量检查 + 重试循环 | `supervisor.py:520`, `should_retry()` |
| Planner 子问题拆解 | `agents/planner.py:352` — `run_planner()` |
| 方法对比专用 Agent | `agents/comparison_agent.py:556` — `run_comparison()` |
| PDF 解析（PyMuPDF） | `services/paper_store.py:25` |
| WebSocket 流式推送 | `web/src/composables/useStreaming.ts` |
