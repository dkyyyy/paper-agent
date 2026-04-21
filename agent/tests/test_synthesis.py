"""Tests for the synthesis agent."""

from types import SimpleNamespace

from app.agents import llm as llm_module
from app.agents.synthesis_agent import (
    SynthesisState,
    _format_papers_info,
    build_synthesis_graph,
    run_synthesis,
)


class StubLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def invoke(self, messages):
        del messages
        if not self._responses:
            raise AssertionError("No more stub responses available")
        return SimpleNamespace(content=self._responses.pop(0))


def sample_papers():
    return [
        {
            "title": "RAG-Fusion",
            "authors": ["Author A", "Author B"],
            "year": 2024,
            "citation_count": 50,
            "extracted_info": {
                "research_question": "How to improve RAG?",
                "method": "Reciprocal rank fusion",
                "dataset": ["NQ", "TriviaQA"],
                "metrics": {"EM": "45.2"},
                "results": "Improved by 5%",
            },
        },
        {
            "title": "Self-RAG",
            "authors": ["Author C"],
            "year": 2023,
            "citation_count": 120,
            "extracted_info": {
                "research_question": "How to make RAG self-reflective?",
                "method": "Self-reflection tokens",
                "dataset": ["PopQA"],
                "metrics": {"EM": "48.1"},
                "results": "SOTA on PopQA",
            },
        },
    ]


def test_graph_builds():
    graph = build_synthesis_graph()
    assert graph is not None
    assert {
        "generate_comparison",
        "generate_survey",
        "generate_timeline",
        "generate_gap_analysis",
        "assemble_report",
    }.issubset(set(graph.get_graph().nodes.keys()))


def test_format_papers_info():
    result = _format_papers_info(sample_papers())
    assert "RAG-Fusion" in result
    assert "Self-RAG" in result
    assert "[1]" in result
    assert "[2]" in result


def test_initial_state():
    state = SynthesisState(
        papers=[],
        topic="RAG optimization",
        task_type="full",
        output="",
        comparison_table="",
        survey_text="",
        timeline="",
        gap_analysis="",
        events=[],
    )
    assert state["task_type"] == "full"


def test_run_synthesis_full(monkeypatch):
    stub_llm = StubLLM(
        [
            "| Paper | Method |\n| --- | --- |\n| RAG-Fusion | RRF |",
            "RAG-Fusion improved retrieval quality and Self-RAG added self-reflection.",
            "2023: Self-RAG.\n2024: RAG-Fusion.",
            "1. Multi-modal grounding remains open.\n2. Evaluation breadth is limited.",
        ]
    )
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)

    result = run_synthesis(sample_papers(), "RAG optimization", task_type="full")

    assert "## Method Comparison" in result["output"]
    assert "## Literature Review" in result["output"]
    assert "## Research Timeline" in result["output"]
    assert "## Research Gaps" in result["output"]
    assert any("Report assembly completed" in event["step"] for event in result["events"])


def test_task_type_controls_generation(monkeypatch):
    stub_llm = StubLLM(
        [
            "| Paper | Method |\n| --- | --- |\n| Self-RAG | Reflection |",
        ]
    )
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)

    result = run_synthesis(sample_papers(), "RAG optimization", task_type="comparison")

    assert result["comparison_table"].startswith("| Paper | Method |")
    assert result["survey_text"] == ""
    assert result["timeline"] == ""
    assert result["gap_analysis"] == ""
    assert "## Method Comparison" in result["output"]
    assert "## Literature Review" not in result["output"]