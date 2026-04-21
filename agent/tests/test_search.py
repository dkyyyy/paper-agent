"""Tests for the search agent."""

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


class FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, tool_name, params):
        return self.store.get((tool_name, json.dumps(params, sort_keys=True)))

    def set(self, tool_name, params, result):
        self.store[(tool_name, json.dumps(params, sort_keys=True))] = result


def test_graph_builds():
    graph = build_search_graph()
    assert graph is not None
    assert {"plan_search", "execute_search", "deduplicate_and_rank"}.issubset(
        set(graph.get_graph().nodes.keys())
    )


def test_arxiv_search_uses_mcp_client_and_cache(monkeypatch):
    fake_cache = FakeCache()
    calls = {"count": 0}

    def fake_call_mcp_tool(server_module, tool_name, arguments):
        calls["count"] += 1
        assert server_module == "app.mcp_servers.arxiv_server"
        assert tool_name == "arxiv_search"
        assert arguments == {"query": "rag", "max_results": 5, "year_from": 2024}
        return [
            {
                "paper_id": "arxiv:2401.12345",
                "title": "RAG Search Paper",
                "source": "arxiv",
            }
        ]

    monkeypatch.setattr(search_module, "search_cache", fake_cache)
    monkeypatch.setattr(search_module, "call_mcp_tool", fake_call_mcp_tool)

    first = _search_arxiv("rag", max_results=5, year_from=2024)
    second = _search_arxiv("rag", max_results=5, year_from=2024)

    assert first[0]["paper_id"] == "arxiv:2401.12345"
    assert second == first
    assert calls["count"] == 1


def test_semantic_scholar_search_uses_mcp_client_and_cache(monkeypatch):
    fake_cache = FakeCache()
    calls = {"count": 0}

    def fake_call_mcp_tool(server_module, tool_name, arguments):
        calls["count"] += 1
        assert server_module == "app.mcp_servers.semantic_scholar"
        assert tool_name == "s2_search"
        assert arguments == {"query": "rag", "max_results": 5, "year_from": 2024}
        return [
            {
                "paper_id": "s2:abc123",
                "title": "Semantic Search Paper",
                "source": "semantic_scholar",
            }
        ]

    monkeypatch.setattr(search_module, "search_cache", fake_cache)
    monkeypatch.setattr(search_module, "call_mcp_tool", fake_call_mcp_tool)

    first = _search_semantic_scholar("rag", max_results=5, year_from=2024)
    second = _search_semantic_scholar("rag", max_results=5, year_from=2024)

    assert first[0]["paper_id"] == "s2:abc123"
    assert second == first
    assert calls["count"] == 1


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
    assert any("Deduplicated and ranked results" in event["step"] for event in result["events"])


def test_run_search_adaptive_expansion(monkeypatch):
    stub_llm = StubLLM(
        [
            json.dumps({"keywords": ["retrieval", "augmented", "generation"]}),
            json.dumps({"queries": ["rag system survey", "retrieval generation benchmark"]}),
        ]
    )
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)
    year_from_values = []

    def fake_arxiv(query, max_results=20, year_from=0):
        del max_results
        year_from_values.append(year_from)
        if query == "retrieval":
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

    def fake_semantic_scholar(query, max_results=20, year_from=0):
        del max_results
        year_from_values.append(year_from)
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

    result = run_search("please review rag", target_count=3)

    assert len(result["papers"]) == 3
    assert result["iteration"] == 2
    assert result["search_queries"] == [
        "retrieval",
        "augmented",
        "generation",
        "rag system survey",
        "retrieval generation benchmark",
    ]
    assert any("Extracted keywords" in event["step"] for event in result["events"])
    assert any("Expanded search" in event["step"] for event in result["events"])
    assert any(event["step"].startswith("Searching ArXiv") for event in result["events"])
    assert year_from_values
    assert all(value == 0 for value in year_from_values)
