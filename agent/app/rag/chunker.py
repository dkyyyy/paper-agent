"""Paper chunking strategy: paragraph, section, and paper-summary levels."""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    content: str
    level: str
    section: str
    chunk_index: int
    paper_id: str
    metadata: dict


SECTION_PATTERNS = [
    r"^#{1,3}\s+(.+)$",
    r"^(\d+\.?\s+[A-Z][A-Za-z\s]+)$",
    r"^(Abstract|Introduction|Related Work|Method|Methodology|Approach|"
    r"Experiment|Evaluation|Results|Discussion|Conclusion|References)"
    r"s?\s*$",
]


def chunk_paragraph(text: str, paper_id: str, chunk_size: int = 512, overlap: int = 50) -> list[Chunk]:
    """Create paragraph-level chunks."""
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks: list[Chunk] = []
    current_section = "unknown"
    buffer = ""
    chunk_index = 0

    for paragraph in paragraphs:
        for pattern in SECTION_PATTERNS:
            match = re.match(pattern, paragraph, re.IGNORECASE | re.MULTILINE)
            if match:
                current_section = match.group(1).strip() if match.groups() else paragraph.strip()
                break

        if buffer and len(buffer) + len(paragraph) > chunk_size:
            chunks.append(
                Chunk(
                    content=buffer.strip(),
                    level="paragraph",
                    section=current_section,
                    chunk_index=chunk_index,
                    paper_id=paper_id,
                    metadata={"char_count": len(buffer)},
                )
            )
            chunk_index += 1
            if overlap > 0 and len(buffer) > overlap:
                buffer = buffer[-overlap:] + "\n\n" + paragraph
            else:
                buffer = paragraph
        else:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph

    if buffer.strip():
        chunks.append(
            Chunk(
                content=buffer.strip(),
                level="paragraph",
                section=current_section,
                chunk_index=chunk_index,
                paper_id=paper_id,
                metadata={"char_count": len(buffer)},
            )
        )

    return chunks


def chunk_section(text: str, paper_id: str, chunk_size: int = 2048, overlap: int = 200) -> list[Chunk]:
    """Create section-level chunks."""
    sections: list[tuple[str, str]] = []
    current_title = "Introduction"
    current_content: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()
        is_header = False
        for pattern in SECTION_PATTERNS:
            if re.match(pattern, stripped, re.IGNORECASE):
                if current_content:
                    sections.append((current_title, "\n".join(current_content)))
                current_title = stripped or current_title
                current_content = []
                is_header = True
                break
        if not is_header:
            current_content.append(line)

    if current_content:
        sections.append((current_title, "\n".join(current_content)))

    chunks: list[Chunk] = []
    for chunk_index, (title, content) in enumerate(sections):
        if len(content) > chunk_size:
            step = max(1, chunk_size - overlap)
            for sub_index, start in enumerate(range(0, len(content), step)):
                part = content[start:start + chunk_size]
                chunks.append(
                    Chunk(
                        content=part.strip(),
                        level="section",
                        section=title,
                        chunk_index=chunk_index * 100 + sub_index,
                        paper_id=paper_id,
                        metadata={"section_title": title},
                    )
                )
        else:
            chunks.append(
                Chunk(
                    content=content.strip(),
                    level="section",
                    section=title,
                    chunk_index=chunk_index,
                    paper_id=paper_id,
                    metadata={"section_title": title},
                )
            )

    return chunks


async def chunk_paper_summary(text: str, paper_id: str, title: str = "") -> Chunk:
    """Create a paper-level summary chunk via LLM."""
    from langchain_core.messages import HumanMessage

    from app.agents.llm import get_llm
    from app.prompts.analysis import PAPER_SUMMARY_PROMPT

    llm = get_llm()
    truncated = text[:15000] if len(text) > 15000 else text
    prompt = PAPER_SUMMARY_PROMPT.format(title=title, content=truncated)
    response = llm.invoke([HumanMessage(content=prompt)])
    summary = getattr(response, "content", response)

    return Chunk(
        content=str(summary),
        level="paper",
        section="summary",
        chunk_index=0,
        paper_id=paper_id,
        metadata={"title": title, "is_llm_summary": True},
    )