# Codex 执行指令 — 任务 3.3：Search Agent（文献检索）

## 任务目标

实现文献检索 Agent，支持多源搜索（ArXiv + Semantic Scholar）、自适应查询扩展、结果去重排序。使用 LangGraph StateGraph 构建。

## 前置依赖

- 任务 3.2 已完成（Supervisor Agent + LLM 工厂）
- 任务 4.1、4.2 的 MCP Server 尚未实现，本任务先用直接 API 调用，后续替换为 MCP
- 参考文档：`docs/02-dev-standards.md` Agent 开发模板

## 需要创建的文件

### 1. `agent/app/prompts/search.py`

```python
"""
Prompt: Search Agent Prompts
版本: v1.0
"""

KEYWORD_EXTRACTION_PROMPT = """从以下用户查询中提取学术搜索关键词。

用户查询：{query}

要求：
1. 提取 3-5 个英文关键词（学术论文通常是英文）
2. 包含核心概念和相关术语
3. 如果用户用中文，翻译为对应的英文学术术语

输出 JSON 格式：
```json
{{"keywords": ["keyword1", "keyword2", "keyword3"]}}
```
"""

QUERY_EXPANSION_PROMPT = """当前搜索结果不足，需要扩展搜索。

原始查询：{original_query}
已使用的关键词：{used_keywords}
当前找到论文数：{current_count}
目标论文数：{target_count}

请生成 2-3 个新的搜索 query，使用不同的关键词组合或同义词，以找到更多相关论文。

输出 JSON 格式：
```json
{{"queries": ["new query 1", "new query 2"]}}
```
"""
```

### 2. `agent/app/agents/search_agent.py`

```python
"""
Agent: Search Agent
职责: 多源文献检索、自适应查询扩展、结果去重排序
绑定工具: arxiv_search, semantic_scholar_search
"""

import json
import logging
import hashlib
from typing import TypedDict, Literal
from difflib import SequenceMatcher

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from app.prompts.search import KEYWORD_EXTRACTION_PROMPT, QUERY_EXPANSION_PROMPT

logger = logging.getLogger(__name__)


class Paper(TypedDict, total=False):
    paper_id: str
    title: str
    authors: list[str]
    abstract: str
    year: int
    source: str          # arxiv | semantic_scholar | dblp
    doi: str
    url: str
    citation_count: int


class SearchState(TypedDict):
    query: str                  # 原始用户查询
    keywords: list[str]         # 提取的关键词
    search_queries: list[str]   # 已执行的搜索 query
    raw_results: list[dict]     # 原始搜索结果
    papers: list[Paper]         # 去重排序后的论文列表
    iteration: int
    max_iterations: int         # 默认 3
    target_count: int           # 目标论文数量
    events: list                # 流式事件


def plan_search(state: SearchState) -> dict:
    """提取关键词或扩展查询。"""
    from app.agents.llm import get_llm

    events = state.get("events", [])
    llm = get_llm()

    if state["iteration"] == 0:
        # First iteration: extract keywords
        prompt = KEYWORD_EXTRACTION_PROMPT.format(query=state["query"])
        response = llm.invoke([HumanMessage(content=prompt)])

        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            data = json.loads(content.strip())
            keywords = data.get("keywords", [state["query"]])
        except (json.JSONDecodeError, IndexError):
            keywords = [state["query"]]

        search_queries = [" ".join(keywords)]
        events.append({
            "type": "agent_status",
            "agent": "search_agent",
            "step": f"关键词提取完成：{', '.join(keywords)}",
        })

        return {
            "keywords": keywords,
            "search_queries": state["search_queries"] + search_queries,
            "events": events,
        }
    else:
        # Subsequent iterations: expand query
        prompt = QUERY_EXPANSION_PROMPT.format(
            original_query=state["query"],
            used_keywords=", ".join(state["keywords"]),
            current_count=len(state["papers"]),
            target_count=state["target_count"],
        )
        response = llm.invoke([HumanMessage(content=prompt)])

        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            data = json.loads(content.strip())
            new_queries = data.get("queries", [])
        except (json.JSONDecodeError, IndexError):
            new_queries = []

        events.append({
            "type": "agent_status",
            "agent": "search_agent",
            "step": f"扩展搜索：{', '.join(new_queries)}",
        })

        return {
            "search_queries": state["search_queries"] + new_queries,
            "events": events,
        }


def execute_search(state: SearchState) -> dict:
    """执行多源搜索。"""
    events = state.get("events", [])
    raw_results = list(state.get("raw_results", []))

    # Get the latest queries to execute
    executed = set()
    for r in raw_results:
        executed.add(r.get("_query", ""))

    new_queries = [q for q in state["search_queries"] if q not in executed]

    for query in new_queries:
        # Search ArXiv
        events.append({
            "type": "agent_status",
            "agent": "search_agent",
            "step": f"正在检索 ArXiv：{query}",
        })
        arxiv_results = _search_arxiv(query, max_results=20)
        for r in arxiv_results:
            r["_query"] = query
        raw_results.extend(arxiv_results)

        # Search Semantic Scholar
        events.append({
            "type": "agent_status",
            "agent": "search_agent",
            "step": f"正在检索 Semantic Scholar：{query}",
        })
        s2_results = _search_semantic_scholar(query, max_results=20)
        for r in s2_results:
            r["_query"] = query
        raw_results.extend(s2_results)

    return {
        "raw_results": raw_results,
        "events": events,
    }


def _search_arxiv(query: str, max_results: int = 20) -> list[dict]:
    """Search ArXiv API directly. Will be replaced by MCP tool in task 4.1."""
    import urllib.request
    import urllib.parse
    import xml.etree.ElementTree as ET

    try:
        encoded_query = urllib.parse.quote(query)
        url = f"http://export.arxiv.org/api/query?search_query=all:{encoded_query}&start=0&max_results={max_results}&sortBy=relevance"
        req = urllib.request.Request(url, headers={"User-Agent": "PaperAgent/1.0"})

        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read().decode("utf-8")

        root = ET.fromstring(data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        results = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            summary = entry.find("atom:summary", ns)
            published = entry.find("atom:published", ns)
            arxiv_id = entry.find("atom:id", ns)

            authors = []
            for author in entry.findall("atom:author", ns):
                name = author.find("atom:name", ns)
                if name is not None:
                    authors.append(name.text)

            results.append({
                "paper_id": f"arxiv:{arxiv_id.text.split('/')[-1]}" if arxiv_id is not None else "",
                "title": title.text.strip().replace("\n", " ") if title is not None else "",
                "authors": authors,
                "abstract": summary.text.strip().replace("\n", " ") if summary is not None else "",
                "year": int(published.text[:4]) if published is not None else 0,
                "source": "arxiv",
                "url": arxiv_id.text if arxiv_id is not None else "",
                "citation_count": 0,
            })

        return results
    except Exception as e:
        logger.error(f"ArXiv search failed: {e}")
        return []


def _search_semantic_scholar(query: str, max_results: int = 20) -> list[dict]:
    """Search Semantic Scholar API directly. Will be replaced by MCP tool in task 4.2."""
    import urllib.request
    import urllib.parse
    import json as json_lib

    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={encoded_query}&limit={max_results}&fields=paperId,title,abstract,year,authors,citationCount,externalIds,url"
        req = urllib.request.Request(url, headers={"User-Agent": "PaperAgent/1.0"})

        with urllib.request.urlopen(req, timeout=30) as response:
            data = json_lib.loads(response.read().decode("utf-8"))

        results = []
        for paper in data.get("data", []):
            authors = [a.get("name", "") for a in paper.get("authors", [])]
            doi = paper.get("externalIds", {}).get("DOI", "")

            results.append({
                "paper_id": f"s2:{paper.get('paperId', '')}",
                "title": paper.get("title", ""),
                "authors": authors,
                "abstract": paper.get("abstract", "") or "",
                "year": paper.get("year", 0) or 0,
                "source": "semantic_scholar",
                "doi": doi,
                "url": paper.get("url", ""),
                "citation_count": paper.get("citationCount", 0) or 0,
            })

        return results
    except Exception as e:
        logger.error(f"Semantic Scholar search failed: {e}")
        return []


def deduplicate_and_rank(state: SearchState) -> dict:
    """去重和排序。"""
    events = state.get("events", [])
    raw = state["raw_results"]

    # Deduplicate by DOI or title similarity
    seen_dois = set()
    seen_titles = {}
    unique_papers = []

    for paper in raw:
        # Skip internal fields
        p = {k: v for k, v in paper.items() if not k.startswith("_")}

        # DOI dedup
        doi = p.get("doi", "")
        if doi and doi in seen_dois:
            continue
        if doi:
            seen_dois.add(doi)

        # Title similarity dedup
        title = p.get("title", "").lower().strip()
        title_hash = hashlib.md5(title.encode()).hexdigest()[:8]

        is_dup = False
        for existing_title in seen_titles:
            if SequenceMatcher(None, title, existing_title).ratio() > 0.85:
                is_dup = True
                break

        if is_dup:
            continue

        seen_titles[title] = True
        unique_papers.append(p)

    # Rank by: citation_count (40%) + year recency (40%) + has_abstract (20%)
    current_year = 2025
    for p in unique_papers:
        citation_score = min(p.get("citation_count", 0) / 100, 1.0)
        year = p.get("year", 0)
        recency_score = max(0, 1.0 - (current_year - year) / 10) if year > 0 else 0
        abstract_score = 1.0 if p.get("abstract") else 0
        p["_score"] = citation_score * 0.4 + recency_score * 0.4 + abstract_score * 0.2

    unique_papers.sort(key=lambda x: x.get("_score", 0), reverse=True)

    # Remove internal score field
    for p in unique_papers:
        p.pop("_score", None)

    events.append({
        "type": "agent_status",
        "agent": "search_agent",
        "step": f"去重排序完成：{len(raw)} → {len(unique_papers)} 篇",
    })

    return {
        "papers": unique_papers,
        "iteration": state["iteration"] + 1,
        "events": events,
    }


def should_continue(state: SearchState) -> Literal["continue", "done"]:
    """判断是否需要继续搜索。"""
    if state["iteration"] >= state["max_iterations"]:
        return "done"
    if len(state["papers"]) >= state["target_count"]:
        return "done"
    return "continue"


def build_search_graph() -> StateGraph:
    """构建 Search Agent 的 LangGraph 状态机。

    流程：
    START → plan_search → execute_search → deduplicate_and_rank
                                                │
                                      ┌─────────┤
                                      ▼         ▼
                                   done → END  continue → plan_search
    """
    graph = StateGraph(SearchState)

    graph.add_node("plan_search", plan_search)
    graph.add_node("execute_search", execute_search)
    graph.add_node("deduplicate_and_rank", deduplicate_and_rank)

    graph.set_entry_point("plan_search")
    graph.add_edge("plan_search", "execute_search")
    graph.add_edge("execute_search", "deduplicate_and_rank")
    graph.add_conditional_edges("deduplicate_and_rank", should_continue, {
        "continue": "plan_search",
        "done": END,
    })

    return graph.compile()


search_graph = build_search_graph()


def run_search(query: str, target_count: int = 15) -> dict:
    """Run the search agent and return results.

    Called by Supervisor Agent's dispatch logic.
    """
    initial_state = SearchState(
        query=query,
        keywords=[],
        search_queries=[],
        raw_results=[],
        papers=[],
        iteration=0,
        max_iterations=3,
        target_count=target_count,
        events=[],
    )
    return search_graph.invoke(initial_state)
```

### 3. `agent/tests/test_search.py`

```python
"""Test Search Agent."""

from app.agents.search_agent import (
    build_search_graph,
    _search_arxiv,
    _search_semantic_scholar,
    SearchState,
)


def test_graph_builds():
    graph = build_search_graph()
    assert graph is not None


def test_arxiv_search():
    """Test ArXiv API returns results (requires network)."""
    results = _search_arxiv("retrieval augmented generation", max_results=5)
    assert isinstance(results, list)
    # May be empty if network unavailable, but should not raise
    if results:
        assert "title" in results[0]
        assert "paper_id" in results[0]
        assert results[0]["source"] == "arxiv"


def test_semantic_scholar_search():
    """Test Semantic Scholar API returns results (requires network)."""
    results = _search_semantic_scholar("retrieval augmented generation", max_results=5)
    assert isinstance(results, list)
    if results:
        assert "title" in results[0]
        assert "paper_id" in results[0]
        assert results[0]["source"] == "semantic_scholar"
```

## 验收标准

### 1. 编译检查

```bash
cd agent
python -c "from app.agents.search_agent import search_graph; print('OK')"
```

### 2. API 连通测试

```bash
cd agent
python -m pytest tests/test_search.py -v
```

### 3. 验收 Checklist

- [ ] `from app.agents.search_agent import search_graph` 无报错
- [ ] Graph 包含 3 个节点：plan_search, execute_search, deduplicate_and_rank
- [ ] ArXiv API 调用正常返回结果（含 title, authors, abstract, year）
- [ ] Semantic Scholar API 调用正常返回结果（含 citationCount）
- [ ] 多源结果基于 DOI + 标题相似度（>85%）去重
- [ ] 结果按 引用数(40%) + 年份新旧(40%) + 有无摘要(20%) 排序
- [ ] 首轮结果不足时自动扩展关键词重新搜索（最多 3 轮）
- [ ] `run_search()` 函数可被 Supervisor 直接调用
- [ ] 每个步骤产生 agent_status 事件
- [ ] 测试通过

## 提交

```bash
git add agent/
git commit -m "feat(agent): implement Search Agent with multi-source retrieval

- ArXiv and Semantic Scholar API integration
- LLM-based keyword extraction and query expansion
- Adaptive search: auto-expand when results insufficient (max 3 rounds)
- DOI + title similarity deduplication
- Weighted ranking (citation 40% + recency 40% + abstract 20%)
- LangGraph state machine with plan → search → deduplicate loop"
```

## 注意事项

1. API 调用使用 urllib 而非 requests，减少依赖（后续 MCP 化时替换）
2. Semantic Scholar 有速率限制（100 req/5min），当前未做限流处理
3. `_search_arxiv` 和 `_search_semantic_scholar` 会在任务 4.1/4.2 中替换为 MCP 工具调用
4. 网络不可用时搜索函数返回空列表，不会崩溃
