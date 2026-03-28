# Codex 执行指令 — 任务 5.3：分层检索器

## 任务目标

实现分层 RAG 检索器，根据问题类型自动选择检索层级（段落/章节/论文），返回相关文档。

## 前置依赖

- 任务 3.4 已完成（Analysis Agent + Chroma 索引）
- `agent/app/rag/embeddings.py` 已存在

## 需要创建的文件

### 1. `agent/app/rag/retriever.py`

```python
"""分层检索器：根据问题类型自动选择检索层级。"""

import json
import logging
from enum import Enum

from langchain_core.messages import HumanMessage

from app.rag.embeddings import get_embeddings
from app.config import config

logger = logging.getLogger(__name__)


class RetrievalLevel(str, Enum):
    PARAGRAPH = "paragraph"   # 细节问题
    SECTION = "section"       # 方法论问题
    PAPER = "paper"           # 跨论文对比问题


LEVEL_DETECTION_PROMPT = """判断以下问题应该在哪个粒度检索论文内容。

问题：{question}

三个粒度：
- paragraph: 细节问题（具体数据、公式、超参数、loss function 等）
- section: 方法论问题（核心方法、实验设计、模型架构等）
- paper: 跨论文问题（多篇论文对比、研究趋势、综合分析等）

只输出一个词：paragraph 或 section 或 paper
"""

LEVEL_TO_COLLECTION = {
    RetrievalLevel.PARAGRAPH: "papers_paragraph",
    RetrievalLevel.SECTION: "papers_section",
    RetrievalLevel.PAPER: "papers_summary",
}


def detect_level(question: str) -> RetrievalLevel:
    """用 LLM 判断问题应该在哪个层级检索。"""
    from app.agents.llm import get_llm

    llm = get_llm()
    prompt = LEVEL_DETECTION_PROMPT.format(question=question)
    response = llm.invoke([HumanMessage(content=prompt)])
    answer = response.content.strip().lower()

    if "paragraph" in answer:
        return RetrievalLevel.PARAGRAPH
    elif "section" in answer:
        return RetrievalLevel.SECTION
    elif "paper" in answer:
        return RetrievalLevel.PAPER
    else:
        return RetrievalLevel.SECTION  # default


def retrieve(
    question: str,
    level: RetrievalLevel | None = None,
    top_k: int = 5,
    paper_id: str | None = None,
) -> list[dict]:
    """检索相关文档。

    Args:
        question: 用户问题
        level: 检索层级，None 则自动检测
        top_k: 返回数量
        paper_id: 限定某篇论文（可选）

    Returns:
        list of {"content": str, "metadata": dict, "score": float}
    """
    import chromadb

    if level is None:
        level = detect_level(question)
        logger.info(f"Auto-detected retrieval level: {level}")

    collection_name = LEVEL_TO_COLLECTION[level]
    embeddings = get_embeddings()

    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    collection = client.get_or_create_collection(collection_name)

    # Build query
    query_embedding = embeddings.embed_query(question)

    where_filter = None
    if paper_id:
        where_filter = {"paper_id": paper_id}

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
    )

    # Format results
    docs = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 0
            docs.append({
                "content": doc,
                "metadata": metadata,
                "score": 1.0 - distance,  # Convert distance to similarity
            })

    return docs
```

### 2. `agent/tests/test_retriever.py`

```python
"""Test retriever level detection logic."""

from app.rag.retriever import RetrievalLevel, LEVEL_TO_COLLECTION


def test_level_to_collection_mapping():
    assert LEVEL_TO_COLLECTION[RetrievalLevel.PARAGRAPH] == "papers_paragraph"
    assert LEVEL_TO_COLLECTION[RetrievalLevel.SECTION] == "papers_section"
    assert LEVEL_TO_COLLECTION[RetrievalLevel.PAPER] == "papers_summary"


def test_retrieval_level_enum():
    assert RetrievalLevel.PARAGRAPH.value == "paragraph"
    assert RetrievalLevel.SECTION.value == "section"
    assert RetrievalLevel.PAPER.value == "paper"
```

## 验收标准

- [ ] `from app.rag.retriever import retrieve` 无报错
- [ ] 细节问题（"用了什么 loss？"）→ 命中 papers_paragraph
- [ ] 方法问题（"核心方法是什么？"）→ 命中 papers_section
- [ ] 对比问题（"这几篇论文区别？"）→ 命中 papers_summary
- [ ] 支持 paper_id 过滤
- [ ] top_k 默认 5，可配置
- [ ] 测试通过

## 提交

```bash
git add agent/app/rag/retriever.py agent/tests/test_retriever.py
git commit -m "feat(agent): implement layered RAG retriever with auto level detection

- LLM-based question type detection (paragraph/section/paper)
- Chroma vector search with metadata filtering
- Support paper_id scoping and configurable top_k"
```
