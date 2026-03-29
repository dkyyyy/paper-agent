"""Embedding model factory for Analysis/RAG pipelines."""

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

    from langchain_community.embeddings import HuggingFaceBgeEmbeddings

    return HuggingFaceBgeEmbeddings(model_name="BAAI/bge-small-zh-v1.5")