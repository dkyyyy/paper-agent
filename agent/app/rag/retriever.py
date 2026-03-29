"""Layered RAG retriever with auto level detection."""

import logging
from enum import Enum
from typing import Any

import chromadb
from langchain_core.messages import HumanMessage

from app.config import config
from app.rag.embeddings import get_embeddings

logger = logging.getLogger(__name__)


class RetrievalLevel(str, Enum):
    PARAGRAPH = "paragraph"
    SECTION = "section"
    PAPER = "paper"


LEVEL_DETECTION_PROMPT = """判断以下问题应该在哪个粒度检索论文内容。
问题：{question}

三个粒度：
- paragraph: 细节问题（具体数据、公式、超参数、loss function 等）
- section: 方法问题（核心方法、实验设计、模型架构等）
- paper: 跨论文问题（多篇论文对比、研究趋势、综合分析等）
只输出一个词：paragraph 或 section 或 paper
"""

LEVEL_TO_COLLECTION = {
    RetrievalLevel.PARAGRAPH: "papers_paragraph",
    RetrievalLevel.SECTION: "papers_section",
    RetrievalLevel.PAPER: "papers_summary",
}


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


def _heuristic_level(question: str) -> RetrievalLevel:
    normalized = question.lower()
    if any(keyword in normalized for keyword in ["loss", "hyperparameter", "公式", "参数", "细节"]):
        return RetrievalLevel.PARAGRAPH
    if any(keyword in normalized for keyword in ["对比", "compare", "difference", "trend", "综述"]):
        return RetrievalLevel.PAPER
    return RetrievalLevel.SECTION


def detect_level(question: str) -> RetrievalLevel:
    """Use the configured LLM to choose retrieval granularity, with heuristic fallback."""
    from app.agents.llm import get_llm

    prompt = LEVEL_DETECTION_PROMPT.format(question=question)
    try:
        llm = get_llm()
        response = llm.invoke([HumanMessage(content=prompt)])
        answer = _response_to_text(response).strip().lower()
    except Exception as exc:
        logger.warning("Level detection via LLM failed, using heuristic fallback: %s", exc)
        return _heuristic_level(question)

    if "paragraph" in answer:
        return RetrievalLevel.PARAGRAPH
    if "section" in answer:
        return RetrievalLevel.SECTION
    if "paper" in answer:
        return RetrievalLevel.PAPER
    return _heuristic_level(question)


def retrieve(
    question: str,
    level: RetrievalLevel | None = None,
    top_k: int = 5,
    paper_id: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve relevant documents from the appropriate Chroma collection."""
    if level is None:
        level = detect_level(question)
        logger.info("Auto-detected retrieval level: %s", level.value)

    collection_name = LEVEL_TO_COLLECTION[level]
    embeddings = get_embeddings()
    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    collection = client.get_or_create_collection(collection_name)

    where_filter = {"paper_id": paper_id} if paper_id else None
    query_embedding = embeddings.embed_query(question)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
    )

    documents: list[dict[str, Any]] = []
    if results and results.get("documents"):
        for index, document in enumerate(results["documents"][0]):
            metadata = results.get("metadatas", [[]])[0][index] if results.get("metadatas") else {}
            distance = results.get("distances", [[]])[0][index] if results.get("distances") else 0.0
            documents.append(
                {
                    "content": document,
                    "metadata": metadata,
                    "score": 1.0 - distance,
                }
            )

    return documents