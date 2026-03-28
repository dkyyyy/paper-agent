# Codex 执行指令 — 任务 3.4：Analysis Agent（论文分析）

## 任务目标

实现论文深度分析 Agent，支持 PDF 解析、五元组提取（Research Question, Method, Dataset, Metric, Result）、分层分块、向量化入库。

## 前置依赖

- 任务 3.2 已完成（Supervisor + LLM 工厂）
- 参考文档：`docs/02-dev-standards.md` Agent 开发模板、RAG 管线规范

## 需要创建的文件

### 1. `agent/app/prompts/analysis.py`

```python
"""
Prompt: Analysis Agent Prompts
版本: v1.0
"""

EXTRACT_INFO_PROMPT = """你是一个学术论文分析专家。请从以下论文内容中提取关键信息。

## 论文内容
{content}

## 提取要求
请提取以下五元组信息，如果某项信息在文中未明确提及，填写 "未明确提及"。

输出 JSON 格式：
```json
{{
  "research_question": "该论文要解决的核心研究问题",
  "method": "提出的核心方法/模型/算法的简要描述",
  "dataset": ["使用的数据集列表"],
  "metrics": {{"指标名": "最佳结果值"}},
  "results": "主要实验结论的一句话总结"
}}
```
"""

SECTION_SUMMARY_PROMPT = """请为以下论文章节生成简洁的学术摘要（100-200字）。

## 章节标题
{section_title}

## 章节内容
{section_content}

要求：
- 保留关键术语和数据
- 使用学术语言
- 不超过 200 字
"""

PAPER_SUMMARY_PROMPT = """请为以下论文生成一段全面的学术摘要（300-500字）。

## 论文标题
{title}

## 论文全文
{content}

要求：
- 涵盖研究背景、方法、实验、结论
- 保留关键数据和结论
- 使用学术语言
- 300-500 字
"""
```

### 2. `agent/app/rag/chunker.py`

```python
"""论文分块策略：三层分块（段落级 / 章节级 / 论文级）。"""

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    content: str
    level: str          # paragraph | section | paper
    section: str        # 所属章节名
    chunk_index: int
    paper_id: str
    metadata: dict


# 常见学术论文章节标题模式
SECTION_PATTERNS = [
    r"^#{1,3}\s+(.+)$",                          # Markdown headers
    r"^(\d+\.?\s+[A-Z][A-Za-z\s]+)$",            # "1. Introduction", "2 Method"
    r"^(Abstract|Introduction|Related Work|Method|Methodology|Approach|"
    r"Experiment|Evaluation|Results|Discussion|Conclusion|References)"
    r"s?\s*$",
]


def chunk_paragraph(text: str, paper_id: str, chunk_size: int = 512, overlap: int = 50) -> list[Chunk]:
    """L1 段落级分块。"""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current_section = "unknown"
    idx = 0

    buffer = ""
    for para in paragraphs:
        # Detect section headers
        for pattern in SECTION_PATTERNS:
            match = re.match(pattern, para, re.IGNORECASE | re.MULTILINE)
            if match:
                current_section = match.group(1).strip() if match.groups() else para.strip()
                break

        if len(buffer) + len(para) > chunk_size and buffer:
            chunks.append(Chunk(
                content=buffer.strip(),
                level="paragraph",
                section=current_section,
                chunk_index=idx,
                paper_id=paper_id,
                metadata={"char_count": len(buffer)},
            ))
            idx += 1
            # Keep overlap
            if overlap > 0 and len(buffer) > overlap:
                buffer = buffer[-overlap:] + "\n\n" + para
            else:
                buffer = para
        else:
            buffer = buffer + "\n\n" + para if buffer else para

    if buffer.strip():
        chunks.append(Chunk(
            content=buffer.strip(),
            level="paragraph",
            section=current_section,
            chunk_index=idx,
            paper_id=paper_id,
            metadata={"char_count": len(buffer)},
        ))

    return chunks


def chunk_section(text: str, paper_id: str, chunk_size: int = 2048, overlap: int = 200) -> list[Chunk]:
    """L2 章节级分块。"""
    # Split by section headers
    sections = []
    current_title = "Introduction"
    current_content = []

    for line in text.split("\n"):
        is_header = False
        for pattern in SECTION_PATTERNS:
            if re.match(pattern, line.strip(), re.IGNORECASE):
                if current_content:
                    sections.append((current_title, "\n".join(current_content)))
                current_title = line.strip()
                current_content = []
                is_header = True
                break
        if not is_header:
            current_content.append(line)

    if current_content:
        sections.append((current_title, "\n".join(current_content)))

    chunks = []
    for idx, (title, content) in enumerate(sections):
        # If section is too long, split further
        if len(content) > chunk_size:
            sub_parts = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size - overlap)]
            for sub_idx, part in enumerate(sub_parts):
                chunks.append(Chunk(
                    content=part.strip(),
                    level="section",
                    section=title,
                    chunk_index=idx * 100 + sub_idx,
                    paper_id=paper_id,
                    metadata={"section_title": title},
                ))
        else:
            chunks.append(Chunk(
                content=content.strip(),
                level="section",
                section=title,
                chunk_index=idx,
                paper_id=paper_id,
                metadata={"section_title": title},
            ))

    return chunks


async def chunk_paper_summary(text: str, paper_id: str, title: str = "") -> Chunk:
    """L3 论文级摘要（需要 LLM 调用）。"""
    from app.agents.llm import get_llm
    from app.prompts.analysis import PAPER_SUMMARY_PROMPT
    from langchain_core.messages import HumanMessage

    llm = get_llm()
    # Truncate if too long for LLM context
    truncated = text[:15000] if len(text) > 15000 else text

    prompt = PAPER_SUMMARY_PROMPT.format(title=title, content=truncated)
    response = llm.invoke([HumanMessage(content=prompt)])

    return Chunk(
        content=response.content,
        level="paper",
        section="summary",
        chunk_index=0,
        paper_id=paper_id,
        metadata={"title": title, "is_llm_summary": True},
    )
```

### 3. `agent/app/rag/embeddings.py`

```python
"""向量化：支持通义千问 Embedding 和本地 BGE 模型。"""

import logging
from functools import lru_cache

from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """Get the embedding model based on config."""
    from app.config import config

    if config.llm_provider == "dashscope":
        from langchain_community.embeddings import DashScopeEmbeddings
        return DashScopeEmbeddings(
            model=config.embedding_model,
            dashscope_api_key=config.llm_api_key,
        )
    else:
        # Fallback: use a simple embedding (for development/testing)
        from langchain_community.embeddings import HuggingFaceBgeEmbeddings
        return HuggingFaceBgeEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
```

### 4. `agent/app/rag/indexer.py`

```python
"""增量索引管理：MD5 去重 + Chroma 入库。"""

import hashlib
import logging

import chromadb
from chromadb.config import Settings

from app.config import config
from app.rag.chunker import Chunk
from app.rag.embeddings import get_embeddings

logger = logging.getLogger(__name__)


def get_chroma_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host=config.chroma_host,
        port=config.chroma_port,
    )


def compute_file_hash(content: str) -> str:
    """Compute MD5 hash of file content."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def is_paper_indexed(paper_id: str, file_hash: str) -> bool:
    """Check if a paper with the same hash is already indexed."""
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection("papers_paragraph")
        results = collection.get(where={"paper_id": paper_id})
        if results and results["ids"]:
            # Check if any existing chunk has the same file_hash
            for meta in results.get("metadatas", []):
                if meta.get("file_hash") == file_hash:
                    return True
    except Exception as e:
        logger.warning(f"Failed to check index: {e}")
    return False


def index_chunks(chunks: list[Chunk], file_hash: str) -> int:
    """Index chunks into Chroma. Returns number of chunks indexed."""
    if not chunks:
        return 0

    client = get_chroma_client()
    embeddings = get_embeddings()

    # Group by level
    by_level = {}
    for chunk in chunks:
        by_level.setdefault(chunk.level, []).append(chunk)

    total = 0
    level_to_collection = {
        "paragraph": "papers_paragraph",
        "section": "papers_section",
        "paper": "papers_summary",
    }

    for level, level_chunks in by_level.items():
        collection_name = level_to_collection.get(level, f"papers_{level}")
        collection = client.get_or_create_collection(collection_name)

        ids = []
        documents = []
        metadatas = []

        for chunk in level_chunks:
            chunk_id = f"{chunk.paper_id}_{chunk.level}_{chunk.chunk_index}"
            ids.append(chunk_id)
            documents.append(chunk.content)
            metadatas.append({
                "paper_id": chunk.paper_id,
                "level": chunk.level,
                "section": chunk.section,
                "chunk_index": chunk.chunk_index,
                "file_hash": file_hash,
                **chunk.metadata,
            })

        # Generate embeddings
        vectors = embeddings.embed_documents(documents)

        # Upsert to Chroma
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=vectors,
            metadatas=metadatas,
        )
        total += len(ids)
        logger.info(f"Indexed {len(ids)} chunks to {collection_name}")

    return total
```

### 5. `agent/app/agents/analysis_agent.py`

```python
"""
Agent: Analysis Agent
职责: 论文深度分析，五元组提取，分层分块，向量化入库
绑定工具: pdf_parser, chunk_indexer
"""

import json
import logging
from typing import TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from app.prompts.analysis import EXTRACT_INFO_PROMPT, SECTION_SUMMARY_PROMPT
from app.rag.chunker import chunk_paragraph, chunk_section, Chunk
from app.rag.indexer import compute_file_hash, is_paper_indexed, index_chunks

logger = logging.getLogger(__name__)


class AnalysisState(TypedDict):
    paper_id: str
    paper_title: str
    paper_content: str          # 全文文本
    file_hash: str
    chunks: list                # 分块结果
    extracted_info: dict        # 五元组
    summary: str                # 论文摘要
    indexed: bool               # 是否已入库
    skipped: bool               # 是否跳过（已存在）
    events: list


def check_duplicate(state: AnalysisState) -> dict:
    """检查论文是否已解析过（MD5 去重）。"""
    events = state.get("events", [])
    content = state["paper_content"]
    file_hash = compute_file_hash(content)

    if is_paper_indexed(state["paper_id"], file_hash):
        events.append({
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": f"论文已存在，跳过重复解析：{state['paper_id']}",
        })
        return {"file_hash": file_hash, "skipped": True, "events": events}

    events.append({
        "type": "agent_status",
        "agent": "analysis_agent",
        "step": f"开始分析论文：{state.get('paper_title', state['paper_id'])}",
    })
    return {"file_hash": file_hash, "skipped": False, "events": events}


def chunk_paper(state: AnalysisState) -> dict:
    """三层分块。"""
    if state.get("skipped"):
        return {}

    events = state.get("events", [])
    content = state["paper_content"]
    paper_id = state["paper_id"]

    # L1: paragraph chunks
    para_chunks = chunk_paragraph(content, paper_id)

    # L2: section chunks
    sec_chunks = chunk_section(content, paper_id)

    all_chunks = para_chunks + sec_chunks
    # L3 (paper summary) is generated in extract_info step

    events.append({
        "type": "agent_status",
        "agent": "analysis_agent",
        "step": f"分块完成：{len(para_chunks)} 段落 + {len(sec_chunks)} 章节",
    })

    return {
        "chunks": [{"content": c.content, "level": c.level, "section": c.section,
                     "chunk_index": c.chunk_index, "paper_id": c.paper_id}
                    for c in all_chunks],
        "events": events,
    }


def extract_info(state: AnalysisState) -> dict:
    """用 LLM 提取五元组 + 生成论文摘要。"""
    if state.get("skipped"):
        return {}

    from app.agents.llm import get_llm

    events = state.get("events", [])
    llm = get_llm()
    content = state["paper_content"]

    # Truncate for LLM context
    truncated = content[:12000] if len(content) > 12000 else content

    # Extract five-tuple
    events.append({
        "type": "agent_status",
        "agent": "analysis_agent",
        "step": "正在提取论文关键信息（五元组）...",
    })

    prompt = EXTRACT_INFO_PROMPT.format(content=truncated)
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        resp_content = response.content
        if "```json" in resp_content:
            resp_content = resp_content.split("```json")[1].split("```")[0]
        extracted = json.loads(resp_content.strip())
    except (json.JSONDecodeError, IndexError):
        extracted = {
            "research_question": "提取失败",
            "method": "提取失败",
            "dataset": [],
            "metrics": {},
            "results": "提取失败",
        }

    # Generate paper summary (L3)
    events.append({
        "type": "agent_status",
        "agent": "analysis_agent",
        "step": "正在生成论文摘要...",
    })

    from app.prompts.analysis import PAPER_SUMMARY_PROMPT
    summary_prompt = PAPER_SUMMARY_PROMPT.format(
        title=state.get("paper_title", ""),
        content=truncated,
    )
    summary_response = llm.invoke([HumanMessage(content=summary_prompt)])
    summary = summary_response.content

    return {
        "extracted_info": extracted,
        "summary": summary,
        "events": events,
    }


def index_to_vectordb(state: AnalysisState) -> dict:
    """向量化入库 Chroma。"""
    if state.get("skipped"):
        return {"indexed": False}

    events = state.get("events", [])

    # Reconstruct Chunk objects
    chunks = []
    for c in state.get("chunks", []):
        chunks.append(Chunk(
            content=c["content"],
            level=c["level"],
            section=c["section"],
            chunk_index=c["chunk_index"],
            paper_id=c["paper_id"],
            metadata={},
        ))

    # Add L3 paper summary chunk
    if state.get("summary"):
        chunks.append(Chunk(
            content=state["summary"],
            level="paper",
            section="summary",
            chunk_index=0,
            paper_id=state["paper_id"],
            metadata={"title": state.get("paper_title", ""), "is_llm_summary": True},
        ))

    try:
        count = index_chunks(chunks, state["file_hash"])
        events.append({
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": f"向量化入库完成：{count} 个 chunks",
        })
        return {"indexed": True, "events": events}
    except Exception as e:
        logger.error(f"Index failed: {e}")
        events.append({
            "type": "agent_status",
            "agent": "analysis_agent",
            "step": f"向量化入库失败：{e}",
        })
        return {"indexed": False, "events": events}


def build_analysis_graph() -> StateGraph:
    """构建 Analysis Agent 的 LangGraph 状态机。

    流程：
    START → check_duplicate → chunk_paper → extract_info → index_to_vectordb → END
    """
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


def run_analysis(paper_id: str, paper_title: str, paper_content: str) -> dict:
    """Run the analysis agent on a single paper.

    Called by Supervisor Agent's dispatch logic.
    """
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
```

### 6. `agent/tests/test_analysis.py`

```python
"""Test Analysis Agent."""

from app.agents.analysis_agent import build_analysis_graph, AnalysisState
from app.rag.chunker import chunk_paragraph, chunk_section


def test_graph_builds():
    graph = build_analysis_graph()
    assert graph is not None


def test_paragraph_chunking():
    text = "\n\n".join([f"This is paragraph {i}. " * 20 for i in range(10)])
    chunks = chunk_paragraph(text, "test_paper_001", chunk_size=512, overlap=50)
    assert len(chunks) > 0
    assert all(c.level == "paragraph" for c in chunks)
    assert all(c.paper_id == "test_paper_001" for c in chunks)


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
    assert all(c.level == "section" for c in chunks)
```

## 验收标准

### 1. 编译检查

```bash
cd agent
python -c "from app.agents.analysis_agent import analysis_graph; print('OK')"
```

### 2. 测试

```bash
cd agent
python -m pytest tests/test_analysis.py -v
```

### 3. 验收 Checklist

- [ ] `from app.agents.analysis_agent import analysis_graph` 无报错
- [ ] Graph 包含 4 个节点：check_duplicate, chunk_paper, extract_info, index_to_vectordb
- [ ] 段落级分块：chunk_size=512, overlap=50，正确分割
- [ ] 章节级分块：按章节标题分割，chunk_size=2048
- [ ] 论文级摘要：LLM 生成 300-500 字摘要
- [ ] 五元组提取：输出 research_question, method, dataset, metrics, results
- [ ] MD5 哈希去重：相同论文不重复解析和入库
- [ ] 向量化入库 Chroma（三个 Collection：papers_paragraph/section/summary）
- [ ] 每个 chunk metadata 包含 paper_id, section, level, chunk_index
- [ ] `run_analysis()` 函数可被 Supervisor 直接调用
- [ ] 测试通过

## 提交

```bash
git add agent/
git commit -m "feat(agent): implement Analysis Agent with layered RAG pipeline

- Three-level chunking: paragraph (512) / section (2048) / paper summary (LLM)
- Five-tuple extraction via LLM (research_question, method, dataset, metrics, results)
- MD5 deduplication: skip already-indexed papers
- Chroma vector indexing with metadata (paper_id, section, level)
- Embedding support for DashScope and BGE models
- LangGraph state machine: check_dup → chunk → extract → index"
```

## 注意事项

1. Chroma 需要运行中才能测试入库（`docker run -p 8000:8000 chromadb/chroma`）
2. 入库测试可在集成测试阶段做，单元测试只验证分块逻辑
3. LLM 调用会截断超长文本（>12000 字符），确保不超出模型上下文窗口
4. `chunk_paper_summary` 是 async 函数，但当前 graph 中用同步方式调用 LLM 生成摘要
