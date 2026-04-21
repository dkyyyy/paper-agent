"""Persistent storage helpers for uploaded papers."""

import hashlib
import logging
from pathlib import Path
from typing import Any

import fitz

from app.config import config
from app.services import db

logger = logging.getLogger(__name__)


def _paths_for_paper(paper_id: str) -> tuple[Path, Path]:
    base_dir = config.ensure_upload_dir()
    return (
        base_dir / f"{paper_id}.pdf",
        base_dir / f"{paper_id}.txt",
    )


def _extract_pdf_metadata(filename: str, file_content: bytes) -> tuple[str, int, str]:
    with fitz.open(stream=file_content, filetype="pdf") as document:
        title = (document.metadata or {}).get("title") or Path(filename).stem
        page_count = document.page_count
        text = "\n\n".join(page.get_text("text").strip() for page in document)
    return title, page_count, text


def save_uploaded_paper(session_id: str, filename: str, file_content: bytes) -> dict[str, Any]:
    """Persist an uploaded PDF to local storage and store metadata in PostgreSQL."""
    file_hash = hashlib.md5(file_content).hexdigest()
    paper_id = f"paper_{file_hash[:16]}"
    pdf_path, text_path = _paths_for_paper(paper_id)
    persisted = db.get_paper(paper_id)

    if persisted and pdf_path.exists() and text_path.exists():
        return {
            "paper_id": paper_id,
            "title": persisted.get("title") or Path(filename).stem,
            "page_count": persisted.get("extracted_info", {}).get("page_count"),
            "file_hash": file_hash,
            "file_path": str(pdf_path),
            "text_path": str(text_path),
        }

    title, page_count, text = _extract_pdf_metadata(filename, file_content)
    pdf_path.write_bytes(file_content)
    text_path.write_text(text, encoding="utf-8")

    metadata = {
        "paper_id": paper_id,
        "session_id": session_id,
        "filename": Path(filename).name,
        "title": title,
        "page_count": page_count,
        "file_hash": file_hash,
        "file_path": str(pdf_path),
        "text_path": str(text_path),
    }
    db.save_paper(
        {
            "paper_id": paper_id,
            "title": title,
            "authors": [],
            "abstract": "",
            "year": None,
            "source": "upload",
            "doi": None,
            "url": "",
            "citation_count": 0,
            "extracted_info": {"page_count": page_count},
            "pdf_path": str(pdf_path),
            "is_indexed": False,
            "file_hash": file_hash,
        }
    )
    logger.info("Stored uploaded paper %s at %s", paper_id, pdf_path)
    return metadata


def get_paper_metadata(paper_id: str) -> dict[str, Any] | None:
    """Load persisted paper metadata by paper id from PostgreSQL."""
    paper = db.get_paper(paper_id)
    if not paper:
        return None
    pdf_path, text_path = _paths_for_paper(paper_id)
    return {
        **paper,
        "file_path": paper.get("pdf_path") or str(pdf_path),
        "text_path": str(text_path),
    }


def get_paper_text(paper_id: str) -> str | None:
    """Load extracted full text for a persisted paper."""
    metadata = get_paper_metadata(paper_id)
    if not metadata:
        return None
    text_path = Path(metadata["text_path"])
    if not text_path.exists():
        return None
    return text_path.read_text(encoding="utf-8")
