# 简历项目描述

## 项目名称 + 一句话定位

**Paper Agent — 基于 LangGraph 的多 Agent 学术研究助手**
`Python / LangGraph / Go / Vue3 / Chroma / Redis / PostgreSQL`

---

## 核心描述（按亮点排，每条都是一个钩子）

**1. 设计并实现了 Supervisor + 多 Agent 协作的编排系统**
基于 LangGraph StateGraph 构建 Supervisor 状态机，通过意图识别将请求路由至 Planner、SearchAgent、AnalysisAgent、SynthesisAgent、ComparisonAgent 五类专用 Agent；Supervisor 内置质量检查节点，规则层（论文数量、输出长度、引用检测）前置过滤后 LLM 评分，不合格自动触发带 feedback 的重试循环。

> 钩子：LangGraph 选型理由 / 状态机设计 / 质量控制机制

**2. 实现了分层 RAG 管线，支持三粒度向量检索**
论文入库时按段落、章节、摘要三级分块写入 Chroma 三个 Collection，检索时由 LLM 动态判断粒度（细节问题→段落，方法问题→章节，跨论文对比→摘要），paper_qa 场景优先走向量检索定位原文段落而非全文摘要截断。

> 钩子：分层 RAG 设计 / 检索粒度决策 / 与普通 RAG 的区别

**3. 封装 MCP Server 工具层，实现 ArXiv / Semantic Scholar 的协议化接入**
将 ArXiv、Semantic Scholar、PDF 解析封装为独立 MCP Server，Agent 通过 stdio 协议动态发现并调用工具，新增数据源无需修改 Agent 代码；SearchAgent 结合 Redis 缓存、LLM 关键词扩展、多轮自适应搜索，去重策略采用 DOI 精确匹配 + 标题 MD5 + 模糊相似度三层过滤。

> 钩子：MCP 协议是什么 / 为什么不直接调 API / 工具扩展性

**4. Go + Python 双服务架构，gRPC Server Streaming 驱动流式输出**
Go Gin 网关负责 WebSocket 长连接、会话路由、文件上传，通过 gRPC Server Streaming 将 Agent 执行事件实时推送至前端；会话层 PostgreSQL 持久化 + Redis 1 小时热缓存双写，TTL 过期后自动从 PostgreSQL 恢复，避免历史丢失。

> 钩子：为什么用 gRPC / Server Streaming 和 SSE 的区别 / 双存储分层设计

**5. 并行化 Agent 执行，分析吞吐量提升约 4 倍**
AnalysisAgent 内部改用 ThreadPoolExecutor 并发分析多篇论文，10 篇论文从串行约 120s 降至约 30s；设计了基于 `depends_on` DAG 的 Plan 结构，为后续 LangGraph Send API 并行调度预留了接口。

> 钩子：并行化方案 / LangGraph Send API / 性能瓶颈在哪

---

## 简历排版（直接复制粘贴）

```
Paper Agent — 多 Agent 学术研究助手                    2025.xx — 2026.xx
Tech: Python / LangGraph / Go(Gin) / gRPC / Chroma / Redis / PostgreSQL / Vue3

• 设计 Supervisor 状态机编排 5 类专用 Agent，内置质量反馈重试循环，
  支持文献综述、方法对比、Research Gap 发现等多场景
• 实现三粒度分层 RAG（段落/章节/摘要），LLM 动态判断检索粒度，
  paper_qa 场景向量检索精确率显著优于全文截断方案
• 封装 ArXiv / Semantic Scholar MCP Server，Agent 运行时动态发现工具，
  新数据源接入无需修改 Agent 代码
• Go 网关通过 gRPC Server Streaming 驱动流式输出，
  PostgreSQL 持久化 + Redis 热缓存双写，TTL 过期自动回源
• 并行化 AnalysisAgent 内部论文处理，吞吐量提升约 4x（120s → 30s）
```

---

## 引导逻辑

每一条描述都留了一个"为什么这样做"的缺口，面试官天然会问：

| 简历里写的 | 面试官大概率问 | 你已准备好的答案位置 |
|-----------|-------------|-------------------|
| LangGraph 状态机 | 为什么不用 if-else / AutoGen | `docs/06-interview-qa.md` Q1 |
| 三粒度 RAG | 检索粒度怎么决策 | Q5 / Q6 |
| MCP Server | MCP 是什么，有什么好处 | Q15（工程细节） |
| 质量反馈重试循环 | LLM 自评怎么保证可靠 | Q4 |
| 4x 性能提升 | 怎么做的并行化 | Q3 |
| gRPC Server Streaming | 为什么不用 HTTP SSE | Q8 |
| PostgreSQL + Redis 双写 | 分层存储的设计思路 | Q9 |
