"""Tests for the Search Agent."""

import json
from types import SimpleNamespace

from app.agents import llm as llm_module
from app.agents import search_agent as search_module
from app.agents.search_agent import (
    SearchState,
    _search_arxiv,
    _search_semantic_scholar,
    build_search_graph,
    deduplicate_and_rank,
    run_search,
)


class StubLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def invoke(self, messages):
        del messages
        if not self._responses:
            raise AssertionError("No more stub responses available")
        return SimpleNamespace(content=self._responses.pop(0))


def test_graph_builds():
    graph = build_search_graph()
    assert graph is not None
    assert {"plan_search", "execute_search", "deduplicate_and_rank"}.issubset(
        set(graph.get_graph().nodes.keys())
    )


def test_arxiv_search():
    """Test ArXiv API returns results (requires network)."""
    results = _search_arxiv("retrieval augmented generation", max_results=5)
    assert isinstance(results, list)
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


def test_deduplicate_and_rank():
    state = SearchState(
        query="rag",
        keywords=[],
        search_queries=[],
        raw_results=[
            {
                "paper_id": "a1",
                "title": "RAG Fusion for Search",
                "authors": ["A"],
                "abstract": "abstract",
                "year": 2025,
                "source": "arxiv",
                "doi": "10.1000/xyz",
                "citation_count": 10,
            },
            {
                "paper_id": "a2",
                "title": "RAG Fusion for Search",
                "authors": ["B"],
                "abstract": "another",
                "year": 2024,
                "source": "semantic_scholar",
                "doi": "10.1000/xyz",
                "citation_count": 99,
            },
            {
                "paper_id": "a3",
                "title": "Self-RAG for Search",
                "authors": ["C"],
                "abstract": "important paper",
                "year": 2026,
                "source": "semantic_scholar",
                "citation_count": 120,
            },
            {
                "paper_id": "a4",
                "title": "Self-RAG for Search.",
                "authors": ["D"],
                "abstract": "similar title",
                "year": 2026,
                "source": "arxiv",
                "citation_count": 80,
            },
        ],
        papers=[],
        iteration=0,
        max_iterations=3,
        target_count=5,
        events=[],
    )

    result = deduplicate_and_rank(state)

    assert len(result["papers"]) == 2
    assert result["papers"][0]["title"] == "Self-RAG for Search"
    assert result["iteration"] == 1
    assert any("去重排序完成" in event["step"] for event in result["events"])


def test_run_search_adaptive_expansion(monkeypatch):
    stub_llm = StubLLM(
        [
            json.dumps({"keywords": ["retrieval", "augmented", "generation"]}),
            json.dumps({"queries": ["rag system survey", "retrieval generation benchmark"]}),
        ]
    )
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)

    def fake_arxiv(query, max_results=20):
        del max_results
        if query == "retrieval augmented generation":
            return [
                {
                    "paper_id": "arxiv:1",
                    "title": "RAG Basics",
                    "authors": ["Author A"],
                    "abstract": "Intro",
                    "year": 2024,
                    "source": "arxiv",
                    "citation_count": 5,
                }
            ]
        if query == "rag system survey":
            return [
                {
                    "paper_id": "arxiv:2",
                    "title": "RAG Survey",
                    "authors": ["Author B"],
                    "abstract": "Survey",
                    "year": 2025,
                    "source": "arxiv",
                    "citation_count": 25,
                }
            ]
        return []

    def fake_semantic_scholar(query, max_results=20):
        del max_results
        if query == "retrieval generation benchmark":
            return [
                {
                    "paper_id": "s2:3",
                    "title": "RAG Benchmarks",
                    "authors": ["Author C"],
                    "abstract": "Benchmarks",
                    "year": 2026,
                    "source": "semantic_scholar",
                    "citation_count": 45,
                }
            ]
        return []

    monkeypatch.setattr(search_module, "_search_arxiv", fake_arxiv)
    monkeypatch.setattr(search_module, "_search_semantic_scholar", fake_semantic_scholar)

    result = run_search("请帮我调研 RAG", target_count=3)

    assert len(result["papers"]) == 3
    assert result["iteration"] == 2
    assert result["search_queries"] == [
        "retrieval augmented generation",
        "rag system survey",
        "retrieval generation benchmark",
    ]
    assert any("关键词提取完成" in event["step"] for event in result["events"])
    assert any("扩展搜索" in event["step"] for event in result["events"])
    assert any(event["step"].startswith("正在检索 ArXiv") for event in result["events"])