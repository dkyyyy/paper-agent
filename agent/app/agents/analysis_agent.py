"""Analysis agent for paper parsing, extraction, and optional vector indexing."""

import json
import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.llm import invoke_llm
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
    persist_to_vectordb: bool
    index_error: str
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
    """Check whether the paper was already indexed via content hash."""
    events = list(state.get("events", []))
    file_hash = compute_file_hash(state["paper_content"])

    if state["persist_to_vectordb"] and is_paper_indexed(state["paper_id"], file_hash):
        events.append(
            {
                "type": "agent_status",
                "agent": "analysis_agent",
                "step": f"Paper already indexed; skipping duplicate analysis: {state['paper_id']}",
            }
        )
        return {"file_hash": file_hash, "skipped": True, "events": events}

    events.append(
        {
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": f"Starting analysis: {state.get('paper_title') or state['paper_id']}",
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
            "step": f"Chunked paper into {len(paragraph_chunks)} paragraph chunks and {len(section_chunks)} section chunks.",
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
    """Extract structured metadata and generate a paper summary."""
    if state.get("skipped"):
        return {}

    events = list(state.get("events", []))
    truncated_content = state["paper_content"][:12000]

    events.append(
        {
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": "Extracting structured paper metadata.",
        }
    )
    extraction_prompt = EXTRACT_INFO_PROMPT.format(content=truncated_content)
    extraction_response = invoke_llm(
        [HumanMessage(content=extraction_prompt)],
        source="analysis.extract_info",
    )

    try:
        extracted_info = json.loads(_extract_json_payload(_response_to_text(extraction_response)))
    except json.JSONDecodeError:
        extracted_info = {
            "research_question": "Extraction failed",
            "method": "Extraction failed",
            "dataset": [],
            "metrics": {},
            "results": "Extraction failed",
        }

    events.append(
        {
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": "Generating paper summary.",
        }
    )
    summary_prompt = PAPER_SUMMARY_PROMPT.format(
        title=state.get("paper_title", ""),
        content=truncated_content,
    )
    summary_response = invoke_llm(
        [HumanMessage(content=summary_prompt)],
        source="analysis.summary",
    )

    return {
        "extracted_info": extracted_info,
        "summary": _response_to_text(summary_response),
        "events": events,
    }


def index_to_vectordb(state: AnalysisState) -> dict[str, Any]:
    """Index chunked paper content into Chroma when enabled."""
    if state.get("skipped"):
        return {"indexed": True, "index_error": ""}

    events = list(state.get("events", []))
    if not state["persist_to_vectordb"]:
        events.append(
            {
                "type": "agent_status",
                "agent": "analysis_agent",
                "step": "Skipping vector indexing because this analysis is based on abstract-only content.",
            }
        )
        return {"indexed": False, "index_error": "", "events": events}

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
                "step": f"Indexed {indexed_count} chunks into Chroma.",
            }
        )
        return {"indexed": True, "index_error": "", "events": events}
    except Exception as exc:
        logger.error("Index failed: %s", exc, exc_info=True)
        events.append(
            {
                "type": "agent_status",
                "agent": "analysis_agent",
                "step": f"Vector indexing failed: {exc}",
            }
        )
        return {"indexed": False, "index_error": str(exc), "events": events}


def build_analysis_graph():
    """Build the analysis agent LangGraph state machine."""
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


def run_analysis(
    paper_id: str,
    paper_title: str,
    paper_content: str,
    persist_to_vectordb: bool = True,
) -> dict[str, Any]:
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
        persist_to_vectordb=persist_to_vectordb,
        index_error="",
        events=[],
    )
    return analysis_graph.invoke(initial_state)