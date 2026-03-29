"""
Agent: Analysis Agent
职责: 论文深度分析、五元组提取、分层分块、向量化入库
绑定工具: pdf_parser, chunk_indexer
"""

import json
import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.prompts.analysis import EXTRACT_INFO_PROMPT, PAPER_SUMMARY_PROMPT
from app.rag.chunker import Chunk, chunk_paragraph, chunk_section
from app.rag.indexer import compute_file_hash, index_chunks, is_paper_indexed

logger = logging.getLogger(__name__)


class AnalysisState(TypedDict):
    paper_id: str
    paper_title: str
    paper_content: str
    file_hash: str
    chunks: list[dict[str, Any]]
    extracted_info: dict[str, Any]
    summary: str
    indexed: bool
    skipped: bool
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


def check_duplicate(state: AnalysisState) -> dict[str, Any]:
    """Check whether the paper was already indexed via MD5 hash."""
    events = list(state.get("events", []))
    file_hash = compute_file_hash(state["paper_content"])

    if is_paper_indexed(state["paper_id"], file_hash):
        events.append(
            {
                "type": "agent_status",
                "agent": "analysis_agent",
                "step": f"论文已存在，跳过重复分析：{state['paper_id']}",
            }
        )
        return {"file_hash": file_hash, "skipped": True, "events": events}

    events.append(
        {
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": f"开始分析论文：{state.get('paper_title') or state['paper_id']}",
        }
    )
    return {"file_hash": file_hash, "skipped": False, "events": events}


def chunk_paper(state: AnalysisState) -> dict[str, Any]:
    """Create paragraph and section chunks for a paper."""
    if state.get("skipped"):
        return {}

    events = list(state.get("events", []))
    paragraph_chunks = chunk_paragraph(state["paper_content"], state["paper_id"])
    section_chunks = chunk_section(state["paper_content"], state["paper_id"])
    all_chunks = paragraph_chunks + section_chunks

    events.append(
        {
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": f"分块完成：{len(paragraph_chunks)} 段落 + {len(section_chunks)} 章节",
        }
    )
    return {
        "chunks": [
            {
                "content": chunk.content,
                "level": chunk.level,
                "section": chunk.section,
                "chunk_index": chunk.chunk_index,
                "paper_id": chunk.paper_id,
                "metadata": chunk.metadata,
            }
            for chunk in all_chunks
        ],
        "events": events,
    }


def extract_info(state: AnalysisState) -> dict[str, Any]:
    """Extract five-tuple metadata and generate a paper summary via LLM."""
    if state.get("skipped"):
        return {}

    from app.agents.llm import get_llm

    events = list(state.get("events", []))
    llm = get_llm()
    truncated_content = state["paper_content"][:12000]

    events.append(
        {
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": "正在提取论文关键信息（五元组）...",
        }
    )
    extraction_prompt = EXTRACT_INFO_PROMPT.format(content=truncated_content)
    extraction_response = llm.invoke([HumanMessage(content=extraction_prompt)])

    try:
        extracted_info = json.loads(_extract_json_payload(_response_to_text(extraction_response)))
    except json.JSONDecodeError:
        extracted_info = {
            "research_question": "提取失败",
            "method": "提取失败",
            "dataset": [],
            "metrics": {},
            "results": "提取失败",
        }

    events.append(
        {
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": "正在生成论文摘要...",
        }
    )
    summary_prompt = PAPER_SUMMARY_PROMPT.format(
        title=state.get("paper_title", ""),
        content=truncated_content,
    )
    summary_response = llm.invoke([HumanMessage(content=summary_prompt)])
    summary = _response_to_text(summary_response)

    return {
        "extracted_info": extracted_info,
        "summary": summary,
        "events": events,
    }


def index_to_vectordb(state: AnalysisState) -> dict[str, Any]:
    """Index chunked paper content into Chroma."""
    if state.get("skipped"):
        return {"indexed": False}

    events = list(state.get("events", []))
    chunks: list[Chunk] = []
    for item in state.get("chunks", []):
        chunks.append(
            Chunk(
                content=item["content"],
                level=item["level"],
                section=item["section"],
                chunk_index=item["chunk_index"],
                paper_id=item["paper_id"],
                metadata=item.get("metadata", {}),
            )
        )

    if state.get("summary"):
        chunks.append(
            Chunk(
                content=state["summary"],
                level="paper",
                section="summary",
                chunk_index=0,
                paper_id=state["paper_id"],
                metadata={"title": state.get("paper_title", ""), "is_llm_summary": True},
            )
        )

    try:
        indexed_count = index_chunks(chunks, state["file_hash"])
        events.append(
            {
                "type": "agent_status",
                "agent": "analysis_agent",
                "step": f"向量化入库完成：{indexed_count} 个 chunks",
            }
        )
        return {"indexed": True, "events": events}
    except Exception as exc:
        logger.error("Index failed: %s", exc)
        events.append(
            {
                "type": "agent_status",
                "agent": "analysis_agent",
                "step": f"向量化入库失败：{exc}",
            }
        )
        return {"indexed": False, "events": events}


def build_analysis_graph():
    """Build the Analysis Agent LangGraph state machine."""
    graph = StateGraph(AnalysisState)
    graph.add_node("check_duplicate", check_duplicate)
    graph.add_node("chunk_paper", chunk_paper)
    graph.add_node("extract_info", extract_info)
    graph.add_node("index_to_vectordb", index_to_vectordb)

    graph.set_entry_point("check_duplicate")
    graph.add_edge("check_duplicate", "chunk_paper")
    graph.add_edge("chunk_paper", "extract_info")
    graph.add_edge("extract_info", "index_to_vectordb")
    graph.add_edge("index_to_vectordb", END)
    return graph.compile()


analysis_graph = build_analysis_graph()


def run_analysis(paper_id: str, paper_title: str, paper_content: str) -> dict[str, Any]:
    """Run the analysis agent on a single paper."""
    initial_state = AnalysisState(
        paper_id=paper_id,
        paper_title=paper_title,
        paper_content=paper_content,
        file_hash="",
        chunks=[],
        extracted_info={},
        summary="",
        indexed=False,
        skipped=False,
        events=[],
    )
    return analysis_graph.invoke(initial_state)