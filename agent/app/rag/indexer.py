"""Incremental Chroma indexing with MD5 deduplication."""

import hashlib
import logging
from typing import Any

import chromadb

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
    """Compute an MD5 hash for the paper content."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def is_paper_indexed(paper_id: str, file_hash: str) -> bool:
    """Check if a paper with the same file hash is already indexed."""
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection("papers_paragraph")
        results = collection.get(where={"paper_id": paper_id})
        if results and results.get("ids"):
            for metadata in results.get("metadatas", []):
                if metadata and metadata.get("file_hash") == file_hash:
                    return True
    except Exception as exc:
        logger.warning("Failed to check index state: %s", exc)
    return False


def index_chunks(chunks: list[Chunk], file_hash: str) -> int:
    """Index chunks into Chroma and return the number of indexed chunks."""
    if not chunks:
        return 0

    client = get_chroma_client()
    embeddings = get_embeddings()
    grouped: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.level, []).append(chunk)

    collection_map = {
        "paragraph": "papers_paragraph",
        "section": "papers_section",
        "paper": "papers_summary",
    }

    total = 0
    for level, group in grouped.items():
        collection = client.get_or_create_collection(collection_map.get(level, f"papers_{level}"))
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for chunk in group:
            ids.append(f"{chunk.paper_id}_{chunk.level}_{chunk.chunk_index}")
            documents.append(chunk.content)
            metadatas.append(
                {
                    "paper_id": chunk.paper_id,
                    "level": chunk.level,
                    "section": chunk.section,
                    "chunk_index": chunk.chunk_index,
                    "file_hash": file_hash,
                    **chunk.metadata,
                }
            )

        vectors = embeddings.embed_documents(documents)
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=vectors,
            metadatas=metadatas,
        )
        total += len(ids)
        logger.info("Indexed %s chunks to %s", len(ids), collection.name)

    return total