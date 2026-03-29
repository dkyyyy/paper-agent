"""
Agent: Synthesis Agent
职责: 跨论文综合分析，生成对比报告、文献综述、时间线与 Research Gap
绑定工具: comparison_table_gen, timeline_gen, report_template
"""

from typing import Any, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.prompts.synthesis import (
    COMPARISON_PROMPT,
    GAP_ANALYSIS_PROMPT,
    SURVEY_PROMPT,
    TIMELINE_PROMPT,
)


class SynthesisState(TypedDict):
    papers: list[dict[str, Any]]
    topic: str
    task_type: str
    output: str
    comparison_table: str
    survey_text: str
    timeline: str
    gap_analysis: str
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


def _format_papers_info(papers: list[dict[str, Any]]) -> str:
    """Format paper metadata for prompt consumption."""
    sections: list[str] = []
    for index, paper in enumerate(papers, start=1):
        info = paper.get("extracted_info", {})
        datasets = info.get("dataset", "N/A")
        if isinstance(datasets, list):
            datasets = ", ".join(datasets)
        sections.append(
            f"""### [{index}] {paper.get('title', 'Unknown Title')}
- 作者: {', '.join(paper.get('authors', [])[:3])}
- 年份: {paper.get('year', 'N/A')}
- 引用数: {paper.get('citation_count', 0)}
- 研究问题: {info.get('research_question', 'N/A')}
- 方法: {info.get('method', 'N/A')}
- 数据集: {datasets}
- 指标: {info.get('metrics', 'N/A')}
- 结果: {info.get('results', 'N/A')}
"""
        )
    return "\n".join(sections)


def generate_comparison(state: SynthesisState) -> dict[str, Any]:
    if state["task_type"] not in {"comparison", "full"}:
        return {}

    from app.agents.llm import get_llm

    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": "正在生成方法对比表格...",
        }
    )

    llm = get_llm()
    prompt = COMPARISON_PROMPT.format(papers_info=_format_papers_info(state["papers"]))
    response = llm.invoke([HumanMessage(content=prompt)])
    return {
        "comparison_table": _response_to_text(response),
        "events": events,
    }


def generate_survey(state: SynthesisState) -> dict[str, Any]:
    if state["task_type"] not in {"survey", "full"}:
        return {}

    from app.agents.llm import get_llm

    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": "正在撰写文献综述...",
        }
    )

    llm = get_llm()
    prompt = SURVEY_PROMPT.format(
        papers_info=_format_papers_info(state["papers"]),
        topic=state["topic"],
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return {
        "survey_text": _response_to_text(response),
        "events": events,
    }


def generate_timeline(state: SynthesisState) -> dict[str, Any]:
    if state["task_type"] not in {"survey", "full"}:
        return {}

    from app.agents.llm import get_llm

    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": "正在梳理研究时间线...",
        }
    )

    llm = get_llm()
    prompt = TIMELINE_PROMPT.format(
        papers_info=_format_papers_info(state["papers"]),
        year1="20XX",
        year2="20XX",
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return {
        "timeline": _response_to_text(response),
        "events": events,
    }


def generate_gap_analysis(state: SynthesisState) -> dict[str, Any]:
    if state["task_type"] not in {"gap_analysis", "full"}:
        return {}

    from app.agents.llm import get_llm

    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": "正在分析 Research Gap...",
        }
    )

    llm = get_llm()
    prompt = GAP_ANALYSIS_PROMPT.format(
        papers_info=_format_papers_info(state["papers"]),
        topic=state["topic"],
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return {
        "gap_analysis": _response_to_text(response),
        "events": events,
    }


def assemble_report(state: SynthesisState) -> dict[str, Any]:
    events = list(state.get("events", []))
    sections: list[str] = []

    if state.get("survey_text"):
        sections.append("## 文献综述\n\n" + state["survey_text"])
    if state.get("comparison_table"):
        sections.append("## 方法对比\n\n" + state["comparison_table"])
    if state.get("timeline"):
        sections.append("## 研究时间线\n\n" + state["timeline"])
    if state.get("gap_analysis"):
        sections.append("## Research Gap 分析\n\n" + state["gap_analysis"])

    output = f"# {state['topic']} - 研究报告\n\n" + "\n\n---\n\n".join(sections)
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": f"报告生成完成（{len(sections)} 个章节）",
        }
    )
    return {
        "output": output,
        "events": events,
    }


def build_synthesis_graph():
    graph = StateGraph(SynthesisState)
    graph.add_node("generate_comparison", generate_comparison)
    graph.add_node("generate_survey", generate_survey)
    graph.add_node("generate_timeline", generate_timeline)
    graph.add_node("generate_gap_analysis", generate_gap_analysis)
    graph.add_node("assemble_report", assemble_report)

    graph.set_entry_point("generate_comparison")
    graph.add_edge("generate_comparison", "generate_survey")
    graph.add_edge("generate_survey", "generate_timeline")
    graph.add_edge("generate_timeline", "generate_gap_analysis")
    graph.add_edge("generate_gap_analysis", "assemble_report")
    graph.add_edge("assemble_report", END)
    return graph.compile()


synthesis_graph = build_synthesis_graph()


def run_synthesis(papers: list[dict[str, Any]], topic: str, task_type: str = "full") -> dict[str, Any]:
    initial_state = SynthesisState(
        papers=papers,
        topic=topic,
        task_type=task_type,
        output="",
        comparison_table="",
        survey_text="",
        timeline="",
        gap_analysis="",
        events=[],
    )
    return synthesis_graph.invoke(initial_state)