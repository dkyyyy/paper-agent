"""Tests for the Analysis Agent."""

import json
from types import SimpleNamespace

from app.agents import llm as llm_module
from app.agents import analysis_agent as analysis_module
from app.agents.analysis_agent import AnalysisState, build_analysis_graph, run_analysis
from app.rag.chunker import chunk_paragraph, chunk_section


class StubLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def invoke(self, messages):
        del messages
        if not self._responses:
            raise AssertionError("No more stub responses available")
        return SimpleNamespace(content=self._responses.pop(0))


def test_graph_builds():
    graph = build_analysis_graph()
    assert graph is not None
    assert {"check_duplicate", "chunk_paper", "extract_info", "index_to_vectordb"}.issubset(
        set(graph.get_graph().nodes.keys())
    )


def test_paragraph_chunking():
    text = "\n\n".join([f"This is paragraph {index}. " * 20 for index in range(10)])
    chunks = chunk_paragraph(text, "test_paper_001", chunk_size=512, overlap=50)
    assert len(chunks) > 0
    assert all(chunk.level == "paragraph" for chunk in chunks)
    assert all(chunk.paper_id == "test_paper_001" for chunk in chunks)


def test_section_chunking():
    text = """# Introduction
This is the introduction section with some content.

# Method
This is the method section describing the approach.

# Experiments
This section presents experimental results.

# Conclusion
This is the conclusion.
"""
    chunks = chunk_section(text, "test_paper_002")
    assert len(chunks) > 0
    assert all(chunk.level == "section" for chunk in chunks)


def test_run_analysis_with_mocks(monkeypatch):
    stub_llm = StubLLM(
        [
            json.dumps(
                {
                    "research_question": "How to improve retrieval quality?",
                    "method": "Hybrid retrieval",
                    "dataset": ["NQ"],
                    "metrics": {"EM": "45.2"},
                    "results": "Improves EM by 5 points.",
                }
            ),
            "This paper proposes a hybrid retrieval method and reports strong gains on NQ.",
        ]
    )
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)
    monkeypatch.setattr(analysis_module, "is_paper_indexed", lambda paper_id, file_hash: False)
    monkeypatch.setattr(analysis_module, "index_chunks", lambda chunks, file_hash: len(chunks))

    result = run_analysis(
        paper_id="paper_001",
        paper_title="Hybrid Retrieval for RAG",
        paper_content="# Introduction\nRAG improves QA.\n\n# Method\nWe use hybrid retrieval.",
    )

    assert result["indexed"] is True
    assert result["skipped"] is False
    assert result["extracted_info"]["method"] == "Hybrid retrieval"
    assert result["summary"].startswith("This paper proposes")
    assert any("开始分析论文" in event["step"] for event in result["events"])
    assert any("向量化入库完成" in event["step"] for event in result["events"])


def test_initial_state():
    state = AnalysisState(
        paper_id="p1",
        paper_title="title",
        paper_content="content",
        file_hash="",
        chunks=[],
        extracted_info={},
        summary="",
        indexed=False,
        skipped=False,
        events=[],
    )
    assert state["paper_id"] == "p1"
    assert state["indexed"] is False