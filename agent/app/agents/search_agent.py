"""
Agent: Search Agent
职责: 多源文献检索、自适应查询扩展、结果去重排序
绑定工具: arxiv_search, semantic_scholar_search
"""

import hashlib
import json
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.prompts.search import KEYWORD_EXTRACTION_PROMPT, QUERY_EXPANSION_PROMPT

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


def plan_search(state: SearchState) -> dict[str, Any]:
    """提取关键词或扩展查询。"""
    from app.agents.llm import get_llm

    events = list(state.get("events", []))
    llm = get_llm()

    if state["iteration"] == 0:
        prompt = KEYWORD_EXTRACTION_PROMPT.format(query=state["query"])
        response = llm.invoke([HumanMessage(content=prompt)])

        try:
            data = json.loads(_extract_json_payload(_response_to_text(response)))
            keywords = data.get("keywords") or [state["query"]]
        except json.JSONDecodeError:
            keywords = [state["query"]]

        search_queries = [" ".join(keywords)]
        events.append(
            {
                "type": "agent_status",
                "agent": "search_agent",
                "step": f"关键词提取完成：{', '.join(keywords)}",
            }
        )
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
    response = llm.invoke([HumanMessage(content=prompt)])

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
            "step": f"扩展搜索：{', '.join(deduped_queries) if deduped_queries else '无新增查询'}",
        }
    )
    return {
        "search_queries": state["search_queries"] + deduped_queries,
        "events": events,
    }


def execute_search(state: SearchState) -> dict[str, Any]:
    """执行多源搜索。"""
    events = list(state.get("events", []))
    raw_results = list(state.get("raw_results", []))
    executed_queries = {result.get("_query", "") for result in raw_results}
    pending_queries = [query for query in state["search_queries"] if query not in executed_queries]

    for query in pending_queries:
        events.append(
            {
                "type": "agent_status",
                "agent": "search_agent",
                "step": f"正在检索 ArXiv：{query}",
            }
        )
        arxiv_results = _search_arxiv(query, max_results=20)
        for result in arxiv_results:
            result["_query"] = query
        raw_results.extend(arxiv_results)

        events.append(
            {
                "type": "agent_status",
                "agent": "search_agent",
                "step": f"正在检索 Semantic Scholar：{query}",
            }
        )
        semantic_results = _search_semantic_scholar(query, max_results=20)
        for result in semantic_results:
            result["_query"] = query
        raw_results.extend(semantic_results)

    return {
        "raw_results": raw_results,
        "events": events,
    }


def _search_arxiv(query: str, max_results: int = 20) -> list[dict[str, Any]]:
    """Search the ArXiv API directly. Will be replaced by MCP in task 4.1."""
    try:
        encoded_query = urllib.parse.quote(query)
        url = (
            "http://export.arxiv.org/api/query?"
            f"search_query=all:{encoded_query}&start=0&max_results={max_results}&sortBy=relevance"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "PaperAgent/1.0"})

        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8")

        root = ET.fromstring(payload)
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        results: list[dict[str, Any]] = []

        for entry in root.findall("atom:entry", namespace):
            title = entry.find("atom:title", namespace)
            summary = entry.find("atom:summary", namespace)
            published = entry.find("atom:published", namespace)
            paper_url = entry.find("atom:id", namespace)
            authors = [
                author.find("atom:name", namespace).text
                for author in entry.findall("atom:author", namespace)
                if author.find("atom:name", namespace) is not None
            ]

            results.append(
                {
                    "paper_id": f"arxiv:{paper_url.text.split('/')[-1]}" if paper_url is not None else "",
                    "title": title.text.strip().replace("\n", " ") if title is not None else "",
                    "authors": authors,
                    "abstract": summary.text.strip().replace("\n", " ") if summary is not None else "",
                    "year": int(published.text[:4]) if published is not None else 0,
                    "source": "arxiv",
                    "url": paper_url.text if paper_url is not None else "",
                    "citation_count": 0,
                }
            )

        return results
    except Exception as exc:
        logger.error("ArXiv search failed: %s", exc)
        return []


def _search_semantic_scholar(query: str, max_results: int = 20) -> list[dict[str, Any]]:
    """Search the Semantic Scholar API directly. Will be replaced by MCP in task 4.2."""
    try:
        encoded_query = urllib.parse.quote(query)
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/search?"
            f"query={encoded_query}&limit={max_results}&"
            "fields=paperId,title,abstract,year,authors,citationCount,externalIds,url"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "PaperAgent/1.0"})

        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        results: list[dict[str, Any]] = []
        for paper in payload.get("data", []):
            results.append(
                {
                    "paper_id": f"s2:{paper.get('paperId', '')}",
                    "title": paper.get("title", ""),
                    "authors": [author.get("name", "") for author in paper.get("authors", [])],
                    "abstract": paper.get("abstract") or "",
                    "year": paper.get("year") or 0,
                    "source": "semantic_scholar",
                    "doi": (paper.get("externalIds") or {}).get("DOI", ""),
                    "url": paper.get("url", ""),
                    "citation_count": paper.get("citationCount") or 0,
                }
            )

        return results
    except Exception as exc:
        logger.error("Semantic Scholar search failed: %s", exc)
        return []


def deduplicate_and_rank(state: SearchState) -> dict[str, Any]:
    """对多源结果进行去重和排序。"""
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
            "step": f"去重排序完成：{len(state['raw_results'])} -> {len(unique_papers)} 篇",
        }
    )
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


def build_search_graph():
    """构建 Search Agent 的 LangGraph 状态机。"""
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


def run_search(query: str, target_count: int = 15) -> dict[str, Any]:
    """Run the search agent and return results."""
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