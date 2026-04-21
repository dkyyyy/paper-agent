"""Search agent for multi-source literature retrieval and ranking."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.llm import invoke_llm
from app.mcp_servers.client import call_mcp_tool
from app.prompts.search import KEYWORD_EXTRACTION_PROMPT, QUERY_EXPANSION_PROMPT
from app.services.cache import search_cache

logger = logging.getLogger(__name__)


class Paper(TypedDict, total=False):
    paper_id: str
    title: str
    authors: list[str]
    abstract: str
    year: int
    source: str
    doi: str
    url: str
    citation_count: int


class SearchState(TypedDict):
    query: str
    keywords: list[str]
    search_queries: list[str]
    raw_results: list[dict[str, Any]]
    papers: list[Paper]
    iteration: int
    max_iterations: int
    target_count: int
    year_from: int
    feedback: str
    events: list[dict[str, str]]


def _response_to_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _extract_json_payload(text: str) -> str:
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text.strip()


def _extract_method_names(query: str) -> list[str]:
    """从查询中提取明确的方法/模型名称（如 RAG-Fusion、Self-RAG、CRAG）。"""
    import re
    # 匹配：含连字符的术语、全大写缩写、驼峰命名
    pattern = r'\b([A-Z][a-zA-Z]*(?:[-][A-Za-z]+)+|[A-Z]{2,}(?:-[A-Za-z]+)*)\b'
    candidates = re.findall(pattern, query)
    # 过滤太短或太泛的通用词
    skip = {"RAG", "LLM", "NLP", "AI", "ML", "API", "GPU", "CPU"}
    results = [c for c in candidates if c not in skip and len(c) >= 3]
    # 对每个方法名追加 "method" 以避免搜到同名基准/数据集
    return [f"{name} method" if len(name) <= 6 else name for name in results]


def plan_search(state: SearchState) -> dict[str, Any]:
    """Generate initial keywords or expand the query adaptively."""
    events = list(state.get("events", []))
    feedback = state.get("feedback", "")

    if state["iteration"] == 0:
        # 有 feedback 说明是 quality_check 触发的重试，用 feedback 重新规划查询
        if feedback:
            prompt = (
                f"上一轮搜索结果被质量审核拒绝，原因如下：\n{feedback}\n\n"
                f"原始用户查询：{state['query']}\n\n"
                "请根据质量反馈，生成 2-3 个更精确的搜索查询词，重点修正上述问题。\n"
                "输出 JSON 格式：\n```json\n{\"keywords\": [\"query1\", \"query2\"]}\n```"
            )
            response = invoke_llm(
                [HumanMessage(content=prompt)],
                source="search.feedback_replanning",
            )
            try:
                data = json.loads(_extract_json_payload(_response_to_text(response)))
                keywords = data.get("keywords") or [state["query"]]
            except json.JSONDecodeError:
                keywords = [state["query"]]
            events.append(
                {
                    "type": "agent_status",
                    "agent": "search_agent",
                    "step": f"Replanning search based on feedback: {', '.join(keywords)}",
                }
            )
        else:
            # 优先检测查询中是否包含明确的方法名
            method_names = _extract_method_names(state["query"])

            if method_names:
                # 直接用方法名作为独立查询，跳过 LLM 关键词提取
                keywords = method_names
                events.append(
                    {
                        "type": "agent_status",
                        "agent": "search_agent",
                        "step": f"Detected method names, searching directly: {', '.join(keywords)}",
                    }
                )
            else:
                # 通用查询走 LLM 关键词提取
                prompt = KEYWORD_EXTRACTION_PROMPT.format(query=state["query"])
                response = invoke_llm(
                    [HumanMessage(content=prompt)],
                    source="search.keyword_extraction",
                )

                try:
                    data = json.loads(_extract_json_payload(_response_to_text(response)))
                    keywords = data.get("keywords") or [state["query"]]
                except json.JSONDecodeError:
                    keywords = [state["query"]]

                events.append(
                    {
                        "type": "agent_status",
                        "agent": "search_agent",
                        "step": f"Extracted keywords: {', '.join(keywords)}",
                    }
                )

        search_queries = keywords  # 每个关键词单独一路查询，不拼接
        return {
            "keywords": keywords,
            "search_queries": state["search_queries"] + search_queries,
            "events": events,
        }

    prompt = QUERY_EXPANSION_PROMPT.format(
        original_query=state["query"],
        used_keywords=", ".join(state["keywords"]),
        current_count=len(state["papers"]),
        target_count=state["target_count"],
    )
    response = invoke_llm(
        [HumanMessage(content=prompt)],
        source="search.query_expansion",
    )

    try:
        data = json.loads(_extract_json_payload(_response_to_text(response)))
        new_queries = data.get("queries", [])
    except json.JSONDecodeError:
        new_queries = []

    deduped_queries = [
        query
        for query in new_queries
        if query and query not in state["search_queries"]
    ]
    events.append(
        {
            "type": "agent_status",
            "agent": "search_agent",
            "step": (
                f"Expanded search with: {', '.join(deduped_queries)}"
                if deduped_queries
                else "No new search queries were generated."
            ),
        }
    )
    return {
        "search_queries": state["search_queries"] + deduped_queries,
        "events": events,
    }


def execute_search(state: SearchState) -> dict[str, Any]:
    """Execute multi-source search for pending queries."""
    import time

    events = list(state.get("events", []))
    raw_results = list(state.get("raw_results", []))
    executed_queries = {result.get("_query", "") for result in raw_results}
    pending_queries = [query for query in state["search_queries"] if query not in executed_queries]

    year_from = state.get("year_from", 0)
    s2_last_request_time = 0.0

    for query in pending_queries:
        # Semantic Scholar 作主数据源（有引用数、相关性好）
        # 限速：确保距上次 S2 请求至少间隔 1.1s
        elapsed = time.time() - s2_last_request_time
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)

        events.append({"type": "agent_status", "agent": "search_agent", "step": f"Searching Semantic Scholar: {query}"})
        s2_results = _search_semantic_scholar(query, max_results=10, year_from=year_from)
        s2_last_request_time = time.time()
        for result in s2_results:
            result["_query"] = query
        raw_results.extend(s2_results)

        # ArXiv 作补充（覆盖预印本，不限速）
        events.append({"type": "agent_status", "agent": "search_agent", "step": f"Searching ArXiv: {query}"})
        arxiv_results = _search_arxiv(query, max_results=10, year_from=year_from)
        for result in arxiv_results:
            result["_query"] = query
        raw_results.extend(arxiv_results)

    return {
        "raw_results": raw_results,
        "events": events,
    }


def _search_arxiv(query: str, max_results: int = 20, year_from: int = 0) -> list[dict[str, Any]]:
    """Search ArXiv through the MCP client."""
    cache_params = {"query": query, "max_results": max_results, "year_from": year_from}
    cached = search_cache.get("arxiv_search", cache_params)
    if cached is not None:
        return cached

    try:
        results = call_mcp_tool(
            "app.mcp_servers.arxiv_server",
            "arxiv_search",
            {
                "query": query,
                "max_results": max_results,
                "year_from": year_from,
            },
        )
    except Exception as exc:
        logger.error("ArXiv MCP search failed: %s", exc, exc_info=True)
        return []

    search_cache.set("arxiv_search", cache_params, results)
    logger.info("ArXiv MCP search returned %d results for query: %s", len(results), query[:100])
    return results


def _search_semantic_scholar(query: str, max_results: int = 20, year_from: int = 0) -> list[dict[str, Any]]:
    """Search Semantic Scholar through the MCP client."""
    cache_params = {"query": query, "max_results": max_results, "year_from": year_from}
    cached = search_cache.get("semantic_scholar_search", cache_params)
    if cached is not None:
        return cached

    try:
        results = call_mcp_tool(
            "app.mcp_servers.semantic_scholar",
            "s2_search",
            {
                "query": query,
                "max_results": max_results,
                "year_from": year_from,
            },
        )
    except Exception as exc:
        logger.error("Semantic Scholar MCP search failed: %s", exc, exc_info=True)
        return []

    search_cache.set("semantic_scholar_search", cache_params, results)
    logger.info("Semantic Scholar MCP search returned %d results for query: %s", len(results), query[:100])
    return results


def deduplicate_and_rank(state: SearchState) -> dict[str, Any]:
    """Deduplicate and rank search results across providers."""
    events = list(state.get("events", []))
    seen_dois: set[str] = set()
    seen_title_hashes: set[str] = set()
    seen_titles: list[str] = []
    unique_papers: list[Paper] = []

    for paper in state["raw_results"]:
        candidate = {key: value for key, value in paper.items() if not key.startswith("_")}
        doi = (candidate.get("doi") or "").strip().lower()
        if doi and doi in seen_dois:
            continue

        title = (candidate.get("title") or "").strip().lower()
        title_hash = hashlib.md5(title.encode("utf-8")).hexdigest() if title else ""
        if title_hash and title_hash in seen_title_hashes:
            continue

        if any(SequenceMatcher(None, title, existing).ratio() > 0.85 for existing in seen_titles):
            continue

        if doi:
            seen_dois.add(doi)
        if title_hash:
            seen_title_hashes.add(title_hash)
        if title:
            seen_titles.append(title)
        unique_papers.append(candidate)

    current_year = datetime.now(timezone.utc).year
    for paper in unique_papers:
        citation_score = min((paper.get("citation_count") or 0) / 100, 1.0)
        year = paper.get("year") or 0
        recency_score = max(0.0, 1.0 - (current_year - year) / 10) if year else 0.0
        abstract_score = 1.0 if paper.get("abstract") else 0.0
        paper["_score"] = citation_score * 0.4 + recency_score * 0.4 + abstract_score * 0.2

    unique_papers.sort(key=lambda paper: paper.get("_score", 0.0), reverse=True)
    for paper in unique_papers:
        paper.pop("_score", None)

    events.append(
        {
            "type": "agent_status",
            "agent": "search_agent",
            "step": f"Deduplicated and ranked results: {len(state['raw_results'])} -> {len(unique_papers)} papers.",
        }
    )
    return {
        "papers": unique_papers,
        "iteration": state["iteration"] + 1,
        "events": events,
    }


def should_continue(state: SearchState) -> Literal["continue", "done"]:
    """Decide whether another search-expansion iteration is needed."""
    if state["iteration"] >= state["max_iterations"]:
        return "done"
    if len(state["papers"]) >= state["target_count"]:
        return "done"
    return "continue"


def build_search_graph():
    """Build the search agent LangGraph state machine."""
    graph = StateGraph(SearchState)
    graph.add_node("plan_search", plan_search)
    graph.add_node("execute_search", execute_search)
    graph.add_node("deduplicate_and_rank", deduplicate_and_rank)

    graph.set_entry_point("plan_search")
    graph.add_edge("plan_search", "execute_search")
    graph.add_edge("execute_search", "deduplicate_and_rank")
    graph.add_conditional_edges(
        "deduplicate_and_rank",
        should_continue,
        {
            "continue": "plan_search",
            "done": END,
        },
    )
    return graph.compile()


search_graph = build_search_graph()


def run_search(query: str, target_count: int = 15, year_from: int = 0, feedback: str = "", max_iterations: int = 3) -> dict[str, Any]:
    """Run the search agent and return ranked literature results."""
    initial_state = SearchState(
        query=query,
        keywords=[],
        search_queries=[],
        raw_results=[],
        papers=[],
        iteration=0,
        max_iterations=max_iterations,
        target_count=target_count,
        year_from=year_from,
        feedback=feedback,
        events=[],
    )
    return search_graph.invoke(initial_state)
