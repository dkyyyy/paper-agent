"""Synthesis agent for cross-paper comparison and report generation."""

from typing import Any, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.llm import invoke_llm
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
    user_query: str
    paper_ids: list[str]
    output: str
    comparison_table: str
    survey_text: str
    timeline: str
    gap_analysis: str
    paper_qa_answer: str
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
        authors = paper.get("authors", [])[:3]
        abstract = (paper.get("abstract") or "").strip()
        summary = (paper.get("summary") or "").strip()
        lines = [
            f"### [{index}] {paper.get('title', 'Unknown Title')}",
            f"- paper_id: {paper.get('paper_id', 'N/A')}",
            f"- Authors: {', '.join(authors) if authors else 'N/A'}",
            f"- Year: {paper.get('year', 'N/A')}",
            f"- Citations: {paper.get('citation_count', 0)}",
            f"- Research question: {info.get('research_question', 'N/A')}",
            f"- Method: {info.get('method', 'N/A')}",
            f"- Dataset: {datasets}",
            f"- Metrics: {info.get('metrics', 'N/A')}",
            f"- Results: {info.get('results', 'N/A')}",
        ]
        if abstract:
            lines.append(f"- Abstract: {abstract}")
        if summary:
            lines.append(f"- Summary: {summary}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def generate_comparison(state: SynthesisState) -> dict[str, Any]:
    if state["task_type"] not in {"comparison", "full"}:
        return {}

    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": "Generating comparison table.",
        }
    )

    prompt = COMPARISON_PROMPT.format(papers_info=_format_papers_info(state["papers"]))
    response = invoke_llm(
        [HumanMessage(content=prompt)],
        source="synthesis.comparison",
    )
    return {
        "comparison_table": _response_to_text(response),
        "events": events,
    }


def generate_survey(state: SynthesisState) -> dict[str, Any]:
    if state["task_type"] not in {"survey", "full"}:
        return {}

    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": "Generating survey narrative.",
        }
    )

    prompt = SURVEY_PROMPT.format(
        papers_info=_format_papers_info(state["papers"]),
        topic=state["topic"],
    )
    response = invoke_llm(
        [HumanMessage(content=prompt)],
        source="synthesis.survey",
    )
    return {
        "survey_text": _response_to_text(response),
        "events": events,
    }


def generate_timeline(state: SynthesisState) -> dict[str, Any]:
    if state["task_type"] not in {"survey", "full"}:
        return {}

    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": "Generating research timeline.",
        }
    )

    prompt = TIMELINE_PROMPT.format(
        papers_info=_format_papers_info(state["papers"]),
        year1="20XX",
        year2="20XX",
    )
    response = invoke_llm(
        [HumanMessage(content=prompt)],
        source="synthesis.timeline",
    )
    return {
        "timeline": _response_to_text(response),
        "events": events,
    }


def generate_paper_qa(state: SynthesisState) -> dict[str, Any]:
    if state["task_type"] != "paper_qa":
        return {}

    from langchain_core.messages import SystemMessage

    from app.rag.retriever import retrieve

    events = list(state.get("events", []))
    user_query = state.get("user_query") or state["topic"]
    paper_ids = state.get("paper_ids") or []

    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": "Retrieving from Chroma for paper_qa.",
        }
    )

    context_chunks: list[dict[str, Any]] = []
    try:
        if paper_ids:
            for pid in paper_ids:
                chunks = retrieve(question=user_query, paper_id=pid, top_k=5)
                context_chunks.extend(chunks)
        else:
            context_chunks = retrieve(question=user_query, top_k=8)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("RAG retrieval failed, falling back to paper abstracts: %s", exc)
        events.append(
            {
                "type": "agent_status",
                "agent": "synthesis_agent",
                "step": f"RAG retrieval failed, using abstract fallback: {exc}",
            }
        )

    if context_chunks:
        context_text = "\n\n---\n\n".join(
            f"[段落 {i + 1}]\n{chunk['content']}"
            for i, chunk in enumerate(context_chunks)
        )
        prompt = (
            f"请根据以下从论文中检索到的段落回答用户问题。\n\n"
            f"用户问题：{user_query}\n\n"
            f"检索到的相关段落：\n{context_text}\n\n"
            f"请基于上述段落给出准确、具体的回答，并引用具体段落内容。"
        )
    else:
        # 回退到全文摘要
        papers_summary = _format_papers_info(state["papers"])
        prompt = (
            f"请根据以下论文内容回答用户问题。\n\n"
            f"用户问题：{user_query}\n\n"
            f"论文内容：\n{papers_summary}"
        )

    response = invoke_llm(
        [SystemMessage(content="你是一个专业的学术论文问答助手。"), HumanMessage(content=prompt)],
        source="synthesis.paper_qa",
    )
    return {
        "paper_qa_answer": _response_to_text(response),
        "events": events,
    }


def generate_gap_analysis(state: SynthesisState) -> dict[str, Any]:
    if state["task_type"] not in {"gap_analysis", "full"}:
        return {}

    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": "Generating research gap analysis.",
        }
    )

    prompt = GAP_ANALYSIS_PROMPT.format(
        papers_info=_format_papers_info(state["papers"]),
        topic=state["topic"],
    )
    response = invoke_llm(
        [HumanMessage(content=prompt)],
        source="synthesis.gap_analysis",
    )
    return {
        "gap_analysis": _response_to_text(response),
        "events": events,
    }


def assemble_report(state: SynthesisState) -> dict[str, Any]:
    events = list(state.get("events", []))
    sections: list[str] = []

    if state.get("paper_qa_answer"):
        sections.append(state["paper_qa_answer"])
    if state.get("survey_text"):
        sections.append("## Literature Review\n\n" + state["survey_text"])
    if state.get("comparison_table"):
        sections.append("## Method Comparison\n\n" + state["comparison_table"])
    if state.get("timeline"):
        sections.append("## Research Timeline\n\n" + state["timeline"])
    if state.get("gap_analysis"):
        sections.append("## Research Gaps\n\n" + state["gap_analysis"])

    output = f"# {state['topic']} - Research Report\n\n" + "\n\n---\n\n".join(sections)
    events.append(
        {
            "type": "agent_status",
            "agent": "synthesis_agent",
            "step": f"Report assembly completed with {len(sections)} sections.",
        }
    )
    return {
        "output": output,
        "events": events,
    }


def build_synthesis_graph():
    graph = StateGraph(SynthesisState)
    graph.add_node("generate_paper_qa", generate_paper_qa)
    graph.add_node("generate_comparison", generate_comparison)
    graph.add_node("generate_survey", generate_survey)
    graph.add_node("generate_timeline", generate_timeline)
    graph.add_node("generate_gap_analysis", generate_gap_analysis)
    graph.add_node("assemble_report", assemble_report)

    graph.set_entry_point("generate_paper_qa")
    graph.add_edge("generate_paper_qa", "generate_comparison")
    graph.add_edge("generate_comparison", "generate_survey")
    graph.add_edge("generate_survey", "generate_timeline")
    graph.add_edge("generate_timeline", "generate_gap_analysis")
    graph.add_edge("generate_gap_analysis", "assemble_report")
    graph.add_edge("assemble_report", END)
    return graph.compile()


synthesis_graph = build_synthesis_graph()


def run_synthesis(
    papers: list[dict[str, Any]],
    topic: str,
    task_type: str = "full",
    user_query: str = "",
    paper_ids: list[str] | None = None,
) -> dict[str, Any]:
    initial_state = SynthesisState(
        papers=papers,
        topic=topic,
        task_type=task_type,
        user_query=user_query or topic,
        paper_ids=paper_ids or [],
        output="",
        comparison_table="",
        survey_text="",
        timeline="",
        gap_analysis="",
        paper_qa_answer="",
        events=[],
    )
    return synthesis_graph.invoke(initial_state)