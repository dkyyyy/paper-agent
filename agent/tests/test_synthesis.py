"""Tests for the Synthesis Agent."""

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
            "[1] RAG-Fusion improved retrieval quality.\n\nReferences\n[1] Author A et al. \"RAG-Fusion\". 2024.",
            "## 研究时间线\n### 2023\n- **Self-RAG** - Introduced reflection tokens.",
            "1. 已覆盖方向\n2. 潜在 Gap\n- 多模态 RAG",
        ]
    )
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)

    result = run_synthesis(sample_papers(), "RAG optimization", task_type="full")

    assert "## 方法对比" in result["output"]
    assert "## 文献综述" in result["output"]
    assert "## 研究时间线" in result["output"]
    assert "## Research Gap 分析" in result["output"]
    assert any("报告生成完成" in event["step"] for event in result["events"])


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
    assert "## 方法对比" in result["output"]
    assert "## 文献综述" not in result["output"]